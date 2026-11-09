import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import TickSighting
from .services import IngestionService, SightingQueryService, ReportService

# Instantiate services
ingestion_service = IngestionService()


def error_response(message, status=400, details=None):
    """
    Standard helper to format clean JSON error payloads.
    """
    payload = {
        'status': status,
        'error': 'Bad Request' if status == 400 else ('Not Found' if status == 404 else 'Error'),
        'message': message
    }
    if details:
        payload['details'] = details
    return JsonResponse(payload, status=status)


@require_http_methods(["GET"])
def api_index(request):
    """
    GET /api/
    Returns an index of all available API endpoints.
    """
    endpoints = {
        'service': 'Elanco UK Tick Sighting Tracker & Analytics API',
        'version': '1.0.0',
        'framework': 'Django (MVC Architecture)',
        'endpoints': {
            'GET /': 'Interactive Web Analytics Dashboard',
            'GET /api/': 'API catalog & documentation (this endpoint)',
            'GET /api/sightings/': 'Search and filter sightings (params: location, species, startDate, endDate, q, page, pageSize)',
            'GET /api/sightings/<id>/': 'Retrieve a specific sighting by ID',
            'GET /api/sightings/city/<city>/': 'Retrieve sightings for a specific city',
            'GET /api/sightings/species/<species>/': 'Retrieve sightings for a specific species',
            'GET /api/reports/summary/': 'National high-level overview metrics',
            'GET /api/reports/by-location/': 'Sightings aggregated by UK city with percentages',
            'GET /api/reports/by-species/': 'Sightings aggregated by tick species with Latin names',
            'GET /api/reports/trends/': 'Longitudinal trends over time (params: interval=monthly|weekly, location, year)',
            'POST /api/sync/': 'Trigger data ingestion from external API',
            'GET /api/sync/status/': 'Check database sync status and record count'
        }
    }
    return JsonResponse(endpoints, json_dumps_params={'indent': 2})


@require_http_methods(["GET"])
def sighting_list(request):
    """
    GET /api/sightings/
    Allows searching and filtering sightings by:
    - location: city name (case-insensitive)
    - species: tick species (case-insensitive)
    - startDate: YYYY-MM-DD or ISO-8601
    - endDate: YYYY-MM-DD or ISO-8601
    - q: free text search query
    - page: page number (default 1)
    - pageSize: items per page (default 20, max 200)
    - sortBy: date, -date, location, species
    """
    location = request.GET.get('location')
    species = request.GET.get('species')
    start_date = request.GET.get('startDate')
    end_date = request.GET.get('endDate')
    query = request.GET.get('q')
    sort_by = request.GET.get('sortBy', '-date')
    page = request.GET.get('page', 1)
    page_size = request.GET.get('pageSize', 20)

    try:
        results = SightingQueryService.search_sightings(
            location=location,
            species=species,
            start_date=start_date,
            end_date=end_date,
            query=query,
            sort_by=sort_by,
            page=page,
            page_size=page_size
        )
        return JsonResponse(results)
    except ValueError as val_err:
        return error_response(str(val_err), status=400)
    except Exception as exc:
        return error_response(f"An unexpected error occurred: {str(exc)}", status=500)


@require_http_methods(["GET"])
def sighting_detail(request, sighting_id):
    """
    GET /api/sightings/<sighting_id>/
    Retrieves full details of a single tick sighting.
    """
    sighting = SightingQueryService.get_by_id(sighting_id)

    if sighting is None:
        return error_response(f"Tick sighting with ID '{sighting_id}' was not found.", status=404)

    return JsonResponse(sighting.to_dict())


@require_http_methods(["GET"])
def sightings_by_city(request, city):
    """
    GET /api/sightings/city/<city>/
    Convenience endpoint matching the upstream API convention.
    """
    page = request.GET.get('page', 1)
    page_size = request.GET.get('pageSize', 50)

    results = SightingQueryService.search_sightings(
        location=city,
        page=page,
        page_size=page_size
    )
    return JsonResponse(results)


@require_http_methods(["GET"])
def sightings_by_species(request, species):
    """
    GET /api/sightings/species/<species>/
    Convenience endpoint matching the upstream API convention.
    """
    page = request.GET.get('page', 1)
    page_size = request.GET.get('pageSize', 50)

    results = SightingQueryService.search_sightings(
        species=species,
        page=page,
        page_size=page_size
    )
    return JsonResponse(results)


@require_http_methods(["GET"])
def report_summary(request):
    """
    GET /api/reports/summary/
    Delivers aggregate national indicators (total counts, top locations, date span).
    """
    summary = ReportService.get_summary()
    return JsonResponse(summary)


@require_http_methods(["GET"])
def report_by_location(request):
    """
    GET /api/reports/by-location/
    Returns number of sightings per UK region, percentages, and dominant species.
    """
    locations = ReportService.get_sightings_by_location()
    return JsonResponse(locations, safe=False)


@require_http_methods(["GET"])
def report_by_species(request):
    """
    GET /api/reports/by-species/
    Returns sightings breakdown by species with Latin binomials.
    """
    species_list = ReportService.get_sightings_by_species()
    return JsonResponse(species_list, safe=False)


@require_http_methods(["GET"])
def report_trends(request):
    """
    GET /api/reports/trends/
    Returns longitudinal trends over time (monthly or weekly).
    Query parameters:
    - interval: 'monthly' (default) or 'weekly'
    - location: optional city filter
    - year: optional year filter (e.g. 2023)
    """
    interval = request.GET.get('interval', 'monthly')
    location = request.GET.get('location')
    year = request.GET.get('year')

    trends = ReportService.get_trends_over_time(
        interval=interval,
        location=location,
        year=year
    )
    return JsonResponse(trends, safe=False)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def sync_data(request):
    """
    POST /api/sync/ -> Triggers ingestion pipeline from external API.
    GET /api/sync/status/ -> Returns current sync status and total database count.
    """
    if request.method == "POST":
        result = ingestion_service.ingest_data()
        status_code = 200 if result['success'] else 500
        return JsonResponse(result, status=status_code)

    # GET request returns status
    total_count = TickSighting.objects.count()
    status_payload = {
        'status': 'HEALTHY',
        'databaseRecords': total_count,
        'message': f"Database currently holds {total_count} tick sightings."
    }
    return JsonResponse(status_payload)


@require_http_methods(["GET"])
def dashboard(request):
    """
    GET /
    Renders an embedded, interactive Web Analytics Dashboard
    with live charts, filterable tables, and direct links to API endpoints.
    """
    # Seed fallback if database is empty on first load
    ingestion_service.seed_if_empty()

    html_content = DASHBOARD_HTML
    return HttpResponse(html_content, content_type="text/html")


# Embedded HTML/JS for dashboard
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Elanco Tick Sighting Tracker & Analytics</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary: #005a9c;
            --primary-dark: #003e6b;
            --secondary: #00a887;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Inter', sans-serif; background-color: var(--bg); color: var(--text-main); padding: 24px; line-height: 1.5; }
        .container { max-width: 1400px; margin: 0 auto; }
        header { display: flex; justify-content: space-between; align-items: center; background: white; padding: 20px 28px; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 24px; }
        .header-title h1 { color: var(--primary); font-size: 22px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        .header-title p { color: var(--text-muted); font-size: 13px; margin-top: 2px; }
        .btn { background: var(--primary); color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 13px; }
        .btn:hover { background: var(--primary-dark); }
        .btn-outline { background: transparent; color: var(--primary); border: 1px solid var(--primary); }
        .btn-outline:hover { background: #e0f2fe; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: white; padding: 18px 20px; border-radius: 10px; border: 1px solid var(--border); }
        .stat-card .label { font-size: 12px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; }
        .stat-card .value { font-size: 28px; font-weight: 700; color: var(--text-main); margin-top: 4px; }
        .stat-card .subtext { font-size: 12px; color: var(--secondary); margin-top: 2px; }
        .tabs { display: flex; gap: 8px; margin-bottom: 20px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
        .tab-btn { padding: 8px 16px; background: none; border: none; font-size: 14px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-radius: 6px; }
        .tab-btn.active { background: #e0f2fe; color: var(--primary); }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .card { background: white; border-radius: 10px; border: 1px solid var(--border); padding: 20px; margin-bottom: 24px; }
        .card-title { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
        .charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        @media(max-width: 860px) { .charts-row { grid-template-columns: 1fr; } }
        .filter-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)) auto; gap: 10px; background: #f1f5f9; padding: 14px; border-radius: 8px; margin-bottom: 16px; align-items: flex-end; }
        .form-group label { display: block; font-size: 11px; font-weight: 600; margin-bottom: 4px; color: var(--text-muted); }
        .form-group input, .form-group select { width: 100%; padding: 6px 10px; border: 1px solid var(--border); border-radius: 4px; font-size: 13px; background: white; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 10px; background: #f8fafc; border-bottom: 2px solid var(--border); color: var(--text-muted); font-size: 11px; text-transform: uppercase; }
        td { padding: 10px; border-bottom: 1px solid var(--border); }
        tr:hover { background-color: #f8fafc; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; background: #e0f2fe; color: #0369a1; }
        .pagination { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; font-size: 12px; color: var(--text-muted); }
        .api-list { display: flex; flex-direction: column; gap: 10px; }
        .api-item { border: 1px solid var(--border); padding: 12px 16px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
        .endpoint-badge { background: #0f172a; color: #38bdf8; font-family: monospace; font-size: 12px; padding: 4px 8px; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>🕷️ Elanco Tick Sighting Tracker</h1>
                <p>Django MVC Backend — UK Epidemiological Data Management & Analytics</p>
            </div>
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-outline" onclick="fetchSummary()">🔄 Refresh</button>
            </div>
        </header>

        <!-- Stats Overview -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Total Records</div>
                <div class="value" id="stat-total">-</div>
                <div class="subtext">SQLite Database</div>
            </div>
            <div class="stat-card">
                <div class="label">UK Cities</div>
                <div class="value" id="stat-locations">-</div>
                <div class="subtext" id="stat-top-loc">Top: Loading...</div>
            </div>
            <div class="stat-card">
                <div class="label">Tick Species</div>
                <div class="value" id="stat-species">-</div>
                <div class="subtext" id="stat-top-spec">Dominant: Loading...</div>
            </div>
            <div class="stat-card">
                <div class="label">Date Span</div>
                <div class="value" style="font-size: 18px; line-height: 2;" id="stat-dates">-</div>
                <div class="subtext">Historical Timeline</div>
            </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('tab-analytics')">📊 Visual Reports & Trends</button>
            <button class="tab-btn" onclick="switchTab('tab-sightings')">🔍 Search & Filter Sightings</button>
            <button class="tab-btn" onclick="switchTab('tab-api')">🔌 API Catalog</button>
        </div>

        <!-- TAB 1: Visual Reports -->
        <div id="tab-analytics" class="tab-content active">
            <div class="charts-row">
                <div class="card">
                    <div class="card-title">Sightings by UK Region</div>
                    <canvas id="chartLocation" height="220"></canvas>
                </div>
                <div class="card">
                    <div class="card-title">Tick Species Breakdown</div>
                    <canvas id="chartSpecies" height="220"></canvas>
                </div>
            </div>
            <div class="card">
                <div class="card-title">Longitudinal Monthly Outbreak Trends</div>
                <canvas id="chartTrends" height="110"></canvas>
            </div>
        </div>

        <!-- TAB 2: Search & Filter Sightings Table -->
        <div id="tab-sightings" class="tab-content">
            <div class="card">
                <div class="filter-bar">
                    <div class="form-group">
                        <label>Location / City</label>
                        <select id="filterLocation" onchange="loadSightings(1)">
                            <option value="">All Cities</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Species</label>
                        <select id="filterSpecies" onchange="loadSightings(1)">
                            <option value="">All Species</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Start Date</label>
                        <input type="date" id="filterStart" onchange="loadSightings(1)">
                    </div>
                    <div class="form-group">
                        <label>End Date</label>
                        <input type="date" id="filterEnd" onchange="loadSightings(1)">
                    </div>
                    <div class="form-group">
                        <label>Search Query</label>
                        <input type="text" id="filterQuery" placeholder="Search..." oninput="debounceSightings()">
                    </div>
                    <div>
                        <button class="btn btn-outline" onclick="resetFilters()">Reset</button>
                    </div>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Date & Time</th>
                            <th>Location</th>
                            <th>Species</th>
                            <th>Latin Name</th>
                        </tr>
                    </thead>
                    <tbody id="sightingsTableBody">
                        <tr><td colspan="5" style="text-align: center;">Loading sightings...</td></tr>
                    </tbody>
                </table>

                <div class="pagination">
                    <span id="pageInfo">Showing page 1</span>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-outline" id="prevPageBtn" onclick="prevPage()">Previous</button>
                        <button class="btn btn-outline" id="nextPageBtn" onclick="nextPage()">Next</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- TAB 3: API Reference -->
        <div id="tab-api" class="tab-content">
            <div class="card">
                <div class="card-title">RESTful API Endpoints</div>
                <div class="api-list">
                    <div class="api-item">
                        <div>
                            <span class="endpoint-badge">GET /api/sightings/</span>
                            <span style="margin-left: 12px; font-weight: 500;">Search & filter sightings (supports pagination, date ranges, location)</span>
                        </div>
                        <a class="btn btn-outline" href="/api/sightings/?pageSize=5" target="_blank">Test JSON</a>
                    </div>
                    <div class="api-item">
                        <div>
                            <span class="endpoint-badge">GET /api/reports/summary/</span>
                            <span style="margin-left: 12px; font-weight: 500;">National summary metrics</span>
                        </div>
                        <a class="btn btn-outline" href="/api/reports/summary/" target="_blank">Test JSON</a>
                    </div>
                    <div class="api-item">
                        <div>
                            <span class="endpoint-badge">GET /api/reports/by-location/</span>
                            <span style="margin-left: 12px; font-weight: 500;">Sightings grouped by UK city</span>
                        </div>
                        <a class="btn btn-outline" href="/api/reports/by-location/" target="_blank">Test JSON</a>
                    </div>
                    <div class="api-item">
                        <div>
                            <span class="endpoint-badge">GET /api/reports/by-species/</span>
                            <span style="margin-left: 12px; font-weight: 500;">Sightings grouped by tick species</span>
                        </div>
                        <a class="btn btn-outline" href="/api/reports/by-species/" target="_blank">Test JSON</a>
                    </div>
                    <div class="api-item">
                        <div>
                            <span class="endpoint-badge">GET /api/reports/trends/?interval=monthly</span>
                            <span style="margin-left: 12px; font-weight: 500;">Trends over time (monthly and weekly)</span>
                        </div>
                        <a class="btn btn-outline" href="/api/reports/trends/?interval=monthly" target="_blank">Test JSON</a>
                    </div>
                    <div class="api-item">
                        <div>
                            <span class="endpoint-badge">POST /api/sync/</span>
                            <span style="margin-left: 12px; font-weight: 500;">Trigger data ingestion from external API</span>
                        </div>
                        <button class="btn btn-outline" onclick="triggerSync()">Trigger Sync</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentPage = 1;
        let totalPages = 1;
        let chartLoc = null;
        let chartSpec = null;
        let chartTrend = null;
        let debounceTimer;

        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }

        async function fetchSummary() {
            try {
                const res = await fetch('/api/reports/summary/');
                const data = await res.json();
                document.getElementById('stat-total').innerText = data.totalSightings.toLocaleString();
                document.getElementById('stat-locations').innerText = data.uniqueLocations;
                document.getElementById('stat-top-loc').innerText = `Top: ${data.topLocation} (${data.topLocationCount})`;
                document.getElementById('stat-species').innerText = data.uniqueSpecies;
                document.getElementById('stat-top-spec').innerText = `Dominant: ${data.topSpecies}`;
                const ear = data.earliestDate ? data.earliestDate.split('T')[0] : '';
                const lat = data.latestDate ? data.latestDate.split('T')[0] : '';
                document.getElementById('stat-dates').innerText = `${ear} to ${lat}`;
                loadCharts();
            } catch(e) { console.error(e); }
        }

        async function loadCharts() {
            // Location Chart
            const locRes = await fetch('/api/reports/by-location/');
            const locData = await locRes.json();
            const locLabels = locData.map(d => d.location);
            const locCounts = locData.map(d => d.sightingCount);

            const selLoc = document.getElementById('filterLocation');
            if (selLoc.options.length <= 1) {
                locLabels.forEach(l => {
                    const opt = document.createElement('option');
                    opt.value = l;
                    opt.innerText = l;
                    selLoc.appendChild(opt);
                });
            }

            if (chartLoc) chartLoc.destroy();
            chartLoc = new Chart(document.getElementById('chartLocation'), {
                type: 'bar',
                data: {
                    labels: locLabels,
                    datasets: [{ label: 'Sightings', data: locCounts, backgroundColor: '#005a9c' }]
                },
                options: { responsive: true, plugins: { legend: { display: false } } }
            });

            // Species Chart
            const specRes = await fetch('/api/reports/by-species/');
            const specData = await specRes.json();
            const specLabels = specData.map(d => d.species);
            const specCounts = specData.map(d => d.count);

            const selSpec = document.getElementById('filterSpecies');
            if (selSpec.options.length <= 1) {
                specLabels.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s;
                    opt.innerText = s;
                    selSpec.appendChild(opt);
                });
            }

            if (chartSpec) chartSpec.destroy();
            chartSpec = new Chart(document.getElementById('chartSpecies'), {
                type: 'doughnut',
                data: {
                    labels: specLabels,
                    datasets: [{ data: specCounts, backgroundColor: ['#005a9c', '#00a887', '#f59e0b', '#8b5cf6', '#ec4899'] }]
                },
                options: { responsive: true }
            });

            // Trends Chart
            const trendRes = await fetch('/api/reports/trends/?interval=monthly');
            const trendData = await trendRes.json();
            const trendLabels = trendData.map(d => d.period);
            const trendCounts = trendData.map(d => d.count);

            if (chartTrend) chartTrend.destroy();
            chartTrend = new Chart(document.getElementById('chartTrends'), {
                type: 'line',
                data: {
                    labels: trendLabels,
                    datasets: [{ label: 'Monthly Sightings', data: trendCounts, borderColor: '#00a887', backgroundColor: 'rgba(0,168,135,0.1)', fill: true, tension: 0.2 }]
                },
                options: { responsive: true }
            });
        }

        async function loadSightings(page = 1) {
            currentPage = page;
            const loc = document.getElementById('filterLocation').value;
            const spec = document.getElementById('filterSpecies').value;
            const start = document.getElementById('filterStart').value;
            const end = document.getElementById('filterEnd').value;
            const q = document.getElementById('filterQuery').value;

            let url = `/api/sightings/?page=${page}&pageSize=15`;
            if (loc) url += `&location=${encodeURIComponent(loc)}`;
            if (spec) url += `&species=${encodeURIComponent(spec)}`;
            if (start) url += `&startDate=${encodeURIComponent(start)}`;
            if (end) url += `&endDate=${encodeURIComponent(end)}`;
            if (q) url += `&q=${encodeURIComponent(q)}`;

            const res = await fetch(url);
            const data = await res.json();

            totalPages = data.totalPages || 1;
            document.getElementById('pageInfo').innerText = `Page ${data.page} of ${data.totalPages} (${data.totalItems} records)`;
            document.getElementById('prevPageBtn').disabled = !data.hasPrevious;
            document.getElementById('nextPageBtn').disabled = !data.hasNext;

            const tbody = document.getElementById('sightingsTableBody');
            tbody.innerHTML = '';

            if (!data.data || data.data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">No sightings match criteria</td></tr>';
                return;
            }

            data.data.forEach(s => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><code>${s.id}</code></td>
                    <td>${s.date.replace('T', ' ')}</td>
                    <td><strong>${s.location}</strong></td>
                    <td><span class="badge">${s.species}</span></td>
                    <td><em>${s.latinName}</em></td>
                `;
                tbody.appendChild(tr);
            });
        }

        function prevPage() { if (currentPage > 1) loadSightings(currentPage - 1); }
        function nextPage() { if (currentPage < totalPages) loadSightings(currentPage + 1); }
        function debounceSightings() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => loadSightings(1), 300);
        }
        function resetFilters() {
            document.getElementById('filterLocation').value = '';
            document.getElementById('filterSpecies').value = '';
            document.getElementById('filterStart').value = '';
            document.getElementById('filterEnd').value = '';
            document.getElementById('filterQuery').value = '';
            loadSightings(1);
        }

        async function triggerSync() {
            const btn = event.target;
            btn.innerText = 'Syncing...';
            btn.disabled = true;
            try {
                const res = await fetch('/api/sync/', { method: 'POST' });
                const json = await res.json();
                alert('Sync complete! ' + json.message + ' (Records: ' + json.inserted_count + ')');
                fetchSummary();
                loadSightings(1);
            } catch(e) {
                alert('Sync error: ' + e);
            } finally {
                btn.innerText = '⚡ Sync API';
                btn.disabled = false;
            }
        }

        // Initialize dashboard
        fetchSummary();
        loadSightings(1);
    </script>
</body>
</html>
"""
