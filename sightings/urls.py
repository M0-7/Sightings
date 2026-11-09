from django.urls import path
from . import views

urlpatterns = [
    # API Catalog Index
    path('api/', views.api_index, name='api_index'),

    # Sightings Search & Details
    path('api/sightings/', views.sighting_list, name='sighting_list'),
    path('api/sightings/<str:sighting_id>/', views.sighting_detail, name='sighting_detail'),
    path('api/sightings/city/<str:city>/', views.sightings_by_city, name='sightings_by_city'),
    path('api/sightings/species/<str:species>/', views.sightings_by_species, name='sightings_by_species'),

    # Aggregate Reporting Endpoints
    path('api/reports/summary/', views.report_summary, name='report_summary'),
    path('api/reports/by-location/', views.report_by_location, name='report_by_location'),
    path('api/reports/by-species/', views.report_by_species, name='report_by_species'),
    path('api/reports/trends/', views.report_trends, name='report_trends'),

    # Data Sync Endpoint
    path('api/sync/', views.sync_data, name='sync_data'),
    path('api/sync/status/', views.sync_data, name='sync_status'),

    # Upstream API path aliases for full compatibility
    path('tick-sightings/', views.sighting_list, name='upstream_sightings'),
    path('tick-sightings/<str:sighting_id>/', views.sighting_detail, name='upstream_sighting_detail'),
    path('tick-sightings/city/<str:city>/', views.sightings_by_city, name='upstream_sightings_by_city'),
    path('tick-sightings/species/<str:species>/', views.sightings_by_species, name='upstream_sightings_by_species'),
    path('stats/', views.report_summary, name='upstream_stats'),

    # Interactive Web Dashboard
    path('', views.dashboard, name='dashboard'),
]
