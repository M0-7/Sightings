from datetime import datetime
from django.test import TestCase, Client
from django.urls import reverse

from .models import TickSighting
from .services import IngestionService, SightingQueryService, ReportService


class TickSightingModelTest(TestCase):
    """
    Tests for the core TickSighting model.
    """

    def setUp(self):
        self.sample_date = datetime(2023, 5, 12, 14, 30, 0)
        self.sighting = TickSighting.objects.create(
            id="test-id-001",
            date=self.sample_date,
            location="London",
            species="Marsh tick",
            latin_name="Ixodes apronophorus"
        )

    def test_model_fields(self):
        self.assertEqual(self.sighting.id, "test-id-001")
        self.assertEqual(self.sighting.location, "London")
        self.assertEqual(self.sighting.species, "Marsh tick")
        self.assertEqual(self.sighting.latin_name, "Ixodes apronophorus")

    def test_to_dict(self):
        data = self.sighting.to_dict()
        self.assertEqual(data['id'], "test-id-001")
        self.assertEqual(data['location'], "London")
        self.assertEqual(data['species'], "Marsh tick")
        self.assertEqual(data['latinName'], "Ixodes apronophorus")
        self.assertTrue("2023-05-12" in data['date'])

    def test_str_representation(self):
        representation = str(self.sighting)
        self.assertTrue("Marsh tick" in representation)
        self.assertTrue("London" in representation)


class IngestionServiceTest(TestCase):
    """
    Tests data validation, cleaning, deduplication, and fallback loading.
    """

    def setUp(self):
        self.service = IngestionService(api_url="http://invalid-url.elanco.test/data")

    def test_validate_and_clean_valid_record(self):
        raw = {
            'id': 'rec-101',
            'date': '2023-04-15T09:30:00',
            'location': '  Manchester  ',
            'species': ' Fox/badger tick ',
            'latinName': ' Ixodes canisuga '
        }
        cleaned = self.service.validate_and_clean_record(raw)
        self.assertIsNotNone(cleaned)
        self.assertEqual(cleaned['id'], 'rec-101')
        self.assertEqual(cleaned['location'], 'Manchester')
        self.assertEqual(cleaned['species'], 'Fox/badger tick')
        self.assertEqual(cleaned['latin_name'], 'Ixodes canisuga')

    def test_validate_discards_incomplete_record(self):
        # Missing ID
        self.assertIsNone(self.service.validate_and_clean_record({
            'date': '2023-04-15T09:30:00',
            'location': 'Manchester',
            'species': 'Marsh tick'
        }))

        # Missing location
        self.assertIsNone(self.service.validate_and_clean_record({
            'id': 'rec-102',
            'date': '2023-04-15T09:30:00',
            'location': '',
            'species': 'Marsh tick'
        }))

        # Invalid date
        self.assertIsNone(self.service.validate_and_clean_record({
            'id': 'rec-103',
            'date': 'not-a-valid-date',
            'location': 'Manchester',
            'species': 'Marsh tick'
        }))

    def test_fallback_ingestion_when_api_offline(self):
        result = self.service.ingest_data()
        self.assertTrue(result['success'])
        self.assertEqual(result['source'], 'FALLBACK_RESOURCE')
        self.assertTrue(result['inserted_count'] > 0)
        self.assertEqual(TickSighting.objects.count(), result['inserted_count'])


class SightingQueryServiceTest(TestCase):
    """
    Tests search, filtering, and pagination.
    """

    def setUp(self):
        TickSighting.objects.create(
            id="s1", date=datetime(2022, 1, 10), location="London",
            species="Marsh tick", latin_name="Ixodes apronophorus"
        )
        TickSighting.objects.create(
            id="s2", date=datetime(2022, 6, 15), location="London",
            species="Fox/badger tick", latin_name="Ixodes canisuga"
        )
        TickSighting.objects.create(
            id="s3", date=datetime(2023, 3, 20), location="Bristol",
            species="Marsh tick", latin_name="Ixodes apronophorus"
        )

    def test_filter_by_location(self):
        res = SightingQueryService.search_sightings(location="London")
        self.assertEqual(res['totalItems'], 2)
        for item in res['data']:
            self.assertEqual(item['location'], "London")

    def test_filter_by_species(self):
        res = SightingQueryService.search_sightings(species="Marsh tick")
        self.assertEqual(res['totalItems'], 2)

    def test_filter_by_date_range(self):
        res = SightingQueryService.search_sightings(
            start_date="2022-01-01",
            end_date="2022-12-31"
        )
        self.assertEqual(res['totalItems'], 2)

    def test_free_text_search_query(self):
        res = SightingQueryService.search_sightings(query="Bristol")
        self.assertEqual(res['totalItems'], 1)
        self.assertEqual(res['data'][0]['id'], "s3")

    def test_invalid_date_raises_error(self):
        with self.assertRaises(ValueError):
            SightingQueryService.search_sightings(start_date="invalid-date")


class ReportServiceTest(TestCase):
    """
    Tests aggregate reports, regional counts, and trends.
    """

    def setUp(self):
        TickSighting.objects.create(
            id="s1", date=datetime(2023, 5, 1), location="London",
            species="Marsh tick", latin_name="Ixodes apronophorus"
        )
        TickSighting.objects.create(
            id="s2", date=datetime(2023, 5, 15), location="London",
            species="Marsh tick", latin_name="Ixodes apronophorus"
        )
        TickSighting.objects.create(
            id="s3", date=datetime(2023, 6, 1), location="Manchester",
            species="Fox/badger tick", latin_name="Ixodes canisuga"
        )

    def test_summary_report(self):
        summary = ReportService.get_summary()
        self.assertEqual(summary['totalSightings'], 3)
        self.assertEqual(summary['uniqueLocations'], 2)
        self.assertEqual(summary['uniqueSpecies'], 2)
        self.assertEqual(summary['topLocation'], "London")
        self.assertEqual(summary['topLocationCount'], 2)

    def test_sightings_by_location(self):
        locations = ReportService.get_sightings_by_location()
        self.assertEqual(len(locations), 2)
        first = locations[0]
        self.assertEqual(first['location'], "London")
        self.assertEqual(first['sightingCount'], 2)
        self.assertEqual(first['percentage'], 66.67)
        self.assertEqual(first['dominantSpecies'], "Marsh tick")

    def test_sightings_by_species(self):
        species_list = ReportService.get_sightings_by_species()
        self.assertEqual(len(species_list), 2)
        first = species_list[0]
        self.assertEqual(first['species'], "Marsh tick")
        self.assertEqual(first['count'], 2)

    def test_trends_over_time(self):
        trends = ReportService.get_trends_over_time(interval='monthly')
        self.assertEqual(len(trends), 2)
        self.assertEqual(trends[0]['period'], "2023-05")
        self.assertEqual(trends[0]['count'], 2)


class ApiEndpointsTest(TestCase):
    """
    Tests HTTP views and JSON API endpoints using Django Test Client.
    """

    def setUp(self):
        self.client = Client()
        TickSighting.objects.create(
            id="api-s1", date=datetime(2023, 4, 10, 12, 0), location="London",
            species="Marsh tick", latin_name="Ixodes apronophorus"
        )

    def test_dashboard_endpoint(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elanco Tick Sighting Tracker")

    def test_api_index_endpoint(self):
        response = self.client.get('/api/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue('endpoints' in data)

    def test_sighting_list_endpoint(self):
        response = self.client.get('/api/sightings/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue('data' in data)
        self.assertEqual(data['totalItems'], 1)

    def test_sighting_detail_found(self):
        response = self.client.get('/api/sightings/api-s1/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], "api-s1")
        self.assertEqual(data['location'], "London")

    def test_sighting_detail_not_found(self):
        response = self.client.get('/api/sightings/non-existent-id/')
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data['status'], 404)

    def test_sightings_by_city_endpoint(self):
        response = self.client.get('/api/sightings/city/London/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['totalItems'], 1)

    def test_reports_summary_endpoint(self):
        response = self.client.get('/api/reports/summary/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['totalSightings'], 1)

    def test_reports_by_location_endpoint(self):
        response = self.client.get('/api/reports/by-location/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

    def test_reports_by_species_endpoint(self):
        response = self.client.get('/api/reports/by-species/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

    def test_reports_trends_endpoint(self):
        response = self.client.get('/api/reports/trends/?interval=monthly')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data) >= 1)

    def test_sync_status_endpoint(self):
        response = self.client.get('/api/sync/status/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'HEALTHY')

    def test_invalid_date_returns_400(self):
        response = self.client.get('/api/sightings/?startDate=bad-date')
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['status'], 400)
