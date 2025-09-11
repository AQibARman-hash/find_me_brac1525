from django.contrib import admin
from .models import User, Location, LocationShare, LocationShareTarget, Friendship, Event, Memory, LocationReview

# Register your models here
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ['location_id', 'location_name', 'pillar_zone', 'location_type', 'is_active']
    list_filter = ['pillar_zone', 'location_type', 'is_active']
    search_fields = ['location_name', 'location_id']

@admin.register(LocationShare)
class LocationShareAdmin(admin.ModelAdmin):
    list_display = ['user', 'location', 'shared_at', 'expires_at', 'is_active', 'status_message']
    list_filter = ['is_active', 'visibility', 'share_type']
    search_fields = ['user__username', 'location__location_name']

@admin.register(LocationShareTarget)
class LocationShareTargetAdmin(admin.ModelAdmin):
    list_display = ['target_user', 'share', 'notification_sent', 'is_seen']

@admin.register(Friendship)
class FriendshipAdmin(admin.ModelAdmin):
    list_display = ['user1', 'user2', 'status', 'created_at']
    list_filter = ['status']

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['event_title', 'organizer', 'location', 'event_start', 'status']
    list_filter = ['event_type', 'status']
    search_fields = ['event_title', 'organizer__username']

@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display = ['memory_title', 'user', 'location', 'creation_date', 'visibility']
    list_filter = ['visibility', 'media_type', 'is_archived']

@admin.register(LocationReview)
class LocationReviewAdmin(admin.ModelAdmin):
    list_display = ['user', 'location', 'rating', 'review_category', 'created_at']
    list_filter = ['rating', 'review_category']    


    