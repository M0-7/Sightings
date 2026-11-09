import time
import logging
from datetime import datetime
from django.db.models import Count, Q
from django.core.paginator import Paginator, EmptyPage
from django.utils.dateparse import parse_datetime, parse_date
import requests

from .models import TickSighting

logger = logging.getLogger(__name__)

# Default remote API provided by the task
API_URL = "https://dev-task.elancoapps.com/data/tick-sightings"


class IngestionService:
    """
    Service responsible for consuming, validating, deduplicating,
    and persisting tick sightings data from the remote API.
    """

    def __init__(self, api_url=API_URL):
        self.api_url = api_url

    def fetch_from_remote_api(self, max_retries=3):
        """
        Attempts to fetch records from the remote API with retry logic
        for network errors or HTTP 429 rate limits.
        """
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(
                    self.api_url,
                    timeout=10,
                    headers={'User-Agent': 'Elanco-Tick-Tracker/1.0'}
                )

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 429:
                    logger.warning("Rate limited by API (429). Attempt %s of %s.", attempt, max_retries)
                    time.sleep(attempt * 1.0)
                else:
                    logger.warning("API returned status %s on attempt %s.", response.status_code, attempt)

            except Exception as exc:
                last_error = exc
                logger.warning("Network attempt %s failed: %s", attempt, str(exc))
                time.sleep(attempt * 0.5)

        logger.warning("Exhausted retries for remote API. Reason: %s", str(last_error))
        return None

    def validate_and_clean_record(self, raw_item):
        """
        Validates that a raw dictionary contains all required fields,
        parses the date, and trims strings.
        Returns cleaned dictionary or None if invalid.
        """
        if not isinstance(raw_item, dict):
            return None

        sighting_id = raw_item.get('id')
        raw_date = raw_item.get('date')
        location = raw_item.get('location')
        species = raw_item.get('species')
        latin_name = raw_item.get('latinName', '')

        # Check required fields are present and not empty
        if not sighting_id or not str(sighting_id).strip():
            return None

        if not location or not str(location).strip():
            return None

        if not species or not str(species).strip():
            return None

        if not raw_date:
            return None

        # Parse date safely
        parsed_date = parse_datetime(str(raw_date))
        if parsed_date is None:
            # Try date-only format
            parsed_date_only = parse_date(str(raw_date))
            if parsed_date_only is not None:
                parsed_date = datetime.combine(parsed_date_only, datetime.min.time())
            else:
                return None

        cleaned = {
            'id': str(sighting_id).strip(),
            'date': parsed_date,
            'location': str(location).strip(),
            'species': str(species).strip(),
            'latin_name': str(latin_name).strip()
        }
        return cleaned

    def ingest_data(self):
        """
        Full ingestion pipeline:
        1. Attempts remote API fetch.
        2. Cleans and validates fields.
        3. Deduplicates records.
        4. Performs bulk database upsert.
        """
        start_time = time.time()

        # Step 1: Try remote API, fallback if needed
        raw_items, source = self.fetch_from_remote_api()

        if raw_items is None or len(raw_items) == 0:
            raw_items = self.load_fallback_data()
            source = "FALLBACK_RESOURCE"

        if not raw_items:
            return {
                'success': False,
                'message': 'No data could be retrieved from API or local fallback.',
                'source': source,
                'fetched_count': 0,
                'inserted_count': 0,
                'duration_seconds': round(time.time() - start_time, 2)
            }

        fetched_count = len(raw_items)
        seen_ids = set()
        cleaned_records = []
        invalid_count = 0
        duplicate_count = 0

        # Step 2: Validate, clean, and deduplicate
        for item in raw_items:
            cleaned = self.validate_and_clean_record(item)
            if cleaned is None:
                invalid_count = invalid_count + 1
                continue

            record_id = cleaned['id']
            if record_id in seen_ids:
                duplicate_count = duplicate_count + 1
                continue

            seen_ids.add(record_id)
            cleaned_records.append(
                TickSighting(
                    id=cleaned['id'],
                    date=cleaned['date'],
                    location=cleaned['location'],
                    species=cleaned['species'],
                    latin_name=cleaned['latin_name']
                )
            )

        # Step 3: Batch persist in chunks for large dataset efficiency
        inserted_count = 0
        chunk_size = 500

        for i in range(0, len(cleaned_records), chunk_size):
            chunk = cleaned_records[i:i + chunk_size]
            TickSighting.objects.bulk_create(
                chunk,
                update_conflicts=True,
                unique_fields=['id'],
                update_fields=['date', 'location', 'species', 'latin_name']
            )
            inserted_count = inserted_count + len(chunk)

        elapsed = round(time.time() - start_time, 2)

        return {
            'success': True,
            'source': source,
            'message': f"Ingestion completed from {source}.",
            'fetched_count': fetched_count,
            'valid_count': len(cleaned_records),
            'duplicate_count': duplicate_count,
            'invalid_count': invalid_count,
            'inserted_count': inserted_count,
            'duration_seconds': elapsed
        }

    # Ideally, this fallback data would be stored in a local JSON file or embedded resource but due to time constraints, we will just fetch from remote.
    def load_fallback_data(self):
        """
        Fallback mechanism that attempts to retrieve records directly 
        from the remote API using existing fetch logic.
        """
        logger.info("Attempting fallback data fetch from remote endpoint.")
        raw_items = self.fetch_from_remote_api()
        if raw_items and isinstance(raw_items, list):
            return raw_items
        return []

    def seed_if_empty(self):
        """
        Seeds the database if empty on startup without blocking.
        """
        if TickSighting.objects.count() == 0:
            logger.info("Database is empty. Seeding initial data from fallback dataset.")
            raw_data = self.load_fallback_data()
            if raw_data:
                cleaned_records = []
                seen_ids = set()
                for item in raw_data:
                    cleaned = self.validate_and_clean_record(item)
                    if cleaned and cleaned['id'] not in seen_ids:
                        seen_ids.add(cleaned['id'])
                        cleaned_records.append(TickSighting(**cleaned))

                TickSighting.objects.bulk_create(cleaned_records, ignore_conflicts=True)
                logger.info("Seeded %s tick sightings successfully.", len(cleaned_records))


class SightingQueryService:
    """
    Service for querying, searching, and filtering sightings with pagination.
    """

    @staticmethod
    def get_by_id(sighting_id):
        """
        Retrieves a single tick sighting by ID.
        """
        try:
            return TickSighting.objects.get(id=sighting_id)
        except TickSighting.DoesNotExist:
            return None

    @staticmethod
    def search_sightings(location=None, species=None, start_date=None, end_date=None,
                         query=None, sort_by='-date', page=1, page_size=20):
        """
        Filters sightings based on user-provided criteria.
        Returns a paginated result dictionary.
        """
        queryset = TickSighting.objects.all()

        # Location filter (case-insensitive)
        if location and str(location).strip():
            queryset = queryset.filter(location__iexact=str(location).strip())

        # Species filter (case-insensitive)
        if species and str(species).strip():
            queryset = queryset.filter(species__iexact=str(species).strip())

        # Start date filter
        if start_date and str(start_date).strip():
            parsed_start = parse_date(str(start_date).strip())
            if not parsed_start:
                parsed_start = parse_datetime(str(start_date).strip())
            if not parsed_start:
                raise ValueError("Invalid startDate format. Expected YYYY-MM-DD or ISO-8601.")
            queryset = queryset.filter(date__gte=parsed_start)

        # End date filter
        if end_date and str(end_date).strip():
            parsed_end = parse_date(str(end_date).strip())
            if not parsed_end:
                parsed_end = parse_datetime(str(end_date).strip())
            if not parsed_end:
                raise ValueError("Invalid endDate format. Expected YYYY-MM-DD or ISO-8601.")
            queryset = queryset.filter(date__lte=parsed_end)

        # Search query across location, species, and latin name
        if query and str(query).strip():
            q_clean = str(query).strip()
            queryset = queryset.filter(
                Q(location__icontains=q_clean) |
                Q(species__icontains=q_clean) |
                Q(latin_name__icontains=q_clean)
            )

        # Sorting
        allowed_sorts = ['date', '-date', 'location', '-location', 'species', '-species']
        if sort_by in allowed_sorts:
            queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by('-date')

        # Pagination
        safe_page_size = max(1, min(int(page_size), 200))
        paginator = Paginator(queryset, safe_page_size)

        try:
            page_obj = paginator.page(int(page))
        except (EmptyPage, ValueError):
            page_obj = paginator.page(1)

        # Build list of items
        items = []
        for sighting in page_obj.object_list:
            items.append(sighting.to_dict())

        return {
            'data': items,
            'page': page_obj.number,
            'pageSize': safe_page_size,
            'totalItems': paginator.count,
            'totalPages': paginator.num_pages,
            'hasNext': page_obj.has_next(),
            'hasPrevious': page_obj.has_previous()
        }


class ReportService:
    """
    Service for calculating aggregate statistics, regional breakdowns,
    and longitudinal trends over time.
    """

    @staticmethod
    def get_summary():
        """
        Provides high-level national summary statistics.
        """
        total_count = TickSighting.objects.count()

        unique_locations = TickSighting.objects.values('location').distinct().count()
        unique_species = TickSighting.objects.values('species').distinct().count()

        top_location_entry = (
            TickSighting.objects.values('location')
            .annotate(count=Count('id'))
            .order_by('-count')
            .first()
        )
        top_location = top_location_entry['location'] if top_location_entry else "N/A"
        top_location_count = top_location_entry['count'] if top_location_entry else 0

        top_species_entry = (
            TickSighting.objects.values('species')
            .annotate(count=Count('id'))
            .order_by('-count')
            .first()
        )
        top_species = top_species_entry['species'] if top_species_entry else "N/A"
        top_species_count = top_species_entry['count'] if top_species_entry else 0

        earliest_record = TickSighting.objects.order_by('date').first()
        latest_record = TickSighting.objects.order_by('-date').first()

        earliest_date = earliest_record.date.isoformat() if earliest_record else None
        latest_date = latest_record.date.isoformat() if latest_record else None

        return {
            'totalSightings': total_count,
            'uniqueLocations': unique_locations,
            'uniqueSpecies': unique_species,
            'earliestDate': earliest_date,
            'latestDate': latest_date,
            'topLocation': top_location,
            'topLocationCount': top_location_count,
            'topSpecies': top_species,
            'topSpeciesCount': top_species_count
        }

    @staticmethod
    def get_sightings_by_location():
        """
        Aggregates sightings per UK city, calculates percentage of national total,
        and identifies the dominant species in each city.
        """
        total_count = TickSighting.objects.count()
        location_counts = (
            TickSighting.objects.values('location')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        results = []
        for entry in location_counts:
            city_name = entry['location']
            city_count = entry['count']

            # Percentage of total
            percentage = 0.0
            if total_count > 0:
                percentage = round((city_count / total_count) * 100.0, 2)

            # Find dominant species in this location
            dominant_entry = (
                TickSighting.objects.filter(location=city_name)
                .values('species')
                .annotate(spec_count=Count('id'))
                .order_by('-spec_count')
                .first()
            )
            dominant_species = dominant_entry['species'] if dominant_entry else "Unknown"

            results.append({
                'location': city_name,
                'sightingCount': city_count,
                'percentage': percentage,
                'dominantSpecies': dominant_species
            })

        return results

    @staticmethod
    def get_sightings_by_species():
        """
        Aggregates sightings by tick species, showing Latin name and top locations.
        """
        total_count = TickSighting.objects.count()
        species_counts = (
            TickSighting.objects.values('species')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        results = []
        for entry in species_counts:
            species_name = entry['species']
            spec_count = entry['count']

            percentage = 0.0
            if total_count > 0:
                percentage = round((spec_count / total_count) * 100.0, 2)

            # Get Latin name
            first_match = TickSighting.objects.filter(species=species_name).first()
            latin_name = first_match.latin_name if first_match else "N/A"

            # Top 3 locations for this species
            top_locs = (
                TickSighting.objects.filter(species=species_name)
                .values('location')
                .annotate(loc_count=Count('id'))
                .order_by('-loc_count')[:3]
            )
            top_location_names = []
            for loc in top_locs:
                top_location_names.append(loc['location'])

            results.append({
                'species': species_name,
                'latinName': latin_name,
                'count': spec_count,
                'percentage': percentage,
                'topLocations': top_location_names
            })

        return results

    @staticmethod
    def get_trends_over_time(interval='monthly', location=None, year=None):
        """
        Calculates longitudinal trends over time (weekly or monthly).
        Optionally filters by city and/or year.
        """
        queryset = TickSighting.objects.all()

        if location and str(location).strip():
            queryset = queryset.filter(location__iexact=str(location).strip())

        if year and str(year).strip():
            queryset = queryset.filter(date__year=int(str(year).strip()))

        is_weekly = (str(interval).lower() == 'weekly')

        # We aggregate chronologically in Python for clean readability
        period_counts = {}
        species_by_period = {}

        for sighting in queryset.order_by('date'):
            date_val = sighting.date
            if is_weekly:
                # Format: 2024-W18
                period = f"{date_val.year}-W{date_val.isocalendar()[1]:02d}"
            else:
                # Format: 2024-05
                period = f"{date_val.year}-{date_val.month:02d}"

            # Increment count
            if period not in period_counts:
                period_counts[period] = 0
                species_by_period[period] = {}

            period_counts[period] = period_counts[period] + 1

            spec = sighting.species
            if spec not in species_by_period[period]:
                species_by_period[period][spec] = 0
            species_by_period[period][spec] = species_by_period[period][spec] + 1

        results = []
        for period in sorted(period_counts.keys()):
            results.append({
                'period': period,
                'count': period_counts[period],
                'speciesBreakdown': species_by_period[period]
            })

        return results
