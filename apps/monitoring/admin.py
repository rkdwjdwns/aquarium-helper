from django.contrib import admin
from .models import (
    Tank, SensorReading, FishBehavior,
    FeedingEvent, FeedingResponse, GrowthRecord,
    ActivityPattern, DeviceControl, EventLog,
)

@admin.register(Tank)
class TankAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'fish_species', 'capacity', 'created_at']

@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'temperature', 'ph', 'dissolved_oxygen', 'turbidity', 'created_at']

@admin.register(FishBehavior)
class FishBehaviorAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'fish_count', 'activity_level', 'status', 'is_anomaly', 'created_at']

@admin.register(FeedingEvent)
class FeedingEventAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'trigger', 'amount_g', 'growth_stage', 'is_overfeeding', 'created_at']

@admin.register(FeedingResponse)
class FeedingResponseAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'frs_score', 'rt_seconds', 'created_at']

@admin.register(GrowthRecord)
class GrowthRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'fish_id', 'estimated_length', 'growth_stage', 'created_at']

@admin.register(ActivityPattern)
class ActivityPatternAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'period_start', 'period_end', 'has_anomaly', 'created_at']

@admin.register(DeviceControl)
class DeviceControlAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'type', 'is_on', 'is_auto', 'last_action_at']

@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'tank', 'level', 'event_type', 'message', 'created_at']