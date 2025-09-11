from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.conf import settings
import json
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class User(AbstractUser):
    """Extended user model with additional campus connection features"""
    
    # Override email to make it unique
    email = models.EmailField(unique=True)
    
    # Your custom fields
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)
    study_preferences = models.JSONField(default=dict, blank=True)
    notification_settings = models.JSONField(default=dict, blank=True)
    last_seen = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Fix the reverse accessor conflicts
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='main_user_set',
        related_query_name='main_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='main_user_set',
        related_query_name='main_user',
    )

    def __str__(self):
        return f"{self.username} ({self.first_name} {self.last_name})"


# Custom Manager Classes (defined before the models)
class LocationManager(models.Manager):
    def get_available_locations(self):
        """Get locations that are active and have available space"""
        return self.filter(is_active=True, free_space_available=True)
    
    def get_by_zone(self, zone):
        """Get locations by pillar zone"""
        return self.filter(pillar_zone=zone, is_active=True)


class FriendshipManager(models.Manager):
    def get_friends(self, user):
        """Get all accepted friends for a user"""
        from django.db import models as django_models
        return User.objects.filter(
            django_models.Q(friendships_received__user1=user, friendships_received__status='accepted') |
            django_models.Q(friendships_initiated__user2=user, friendships_initiated__status='accepted')
        ).distinct()
    
    def are_friends(self, user1, user2):
        """Check if two users are friends"""
        from django.db import models as django_models
        return self.filter(
            django_models.Q(user1=user1, user2=user2, status='accepted') |
            django_models.Q(user1=user2, user2=user1, status='accepted')
        ).exists()


class Location(models.Model):
    """Campus locations including pillars and free spaces"""
    PILLAR_ZONES = [
        ('A', 'Zone A'),
        ('B', 'Zone B'), 
        ('C', 'Zone C'),
        ('FS', 'Free Space'),
    ]
    
    LOCATION_TYPES = [
        ('pillar', 'Pillar'),
        ('study_area', 'Study Area'),
        ('common_area', 'Common Area'),
    ]
    
    CROWD_LEVELS = [
        ('light', 'Light'),
        ('moderate', 'Moderate'),
        ('heavy', 'Heavy'),
    ]

    location_id = models.CharField(primary_key=True, max_length=10)  # "P01_A", "FS_01"
    pillar_zone = models.CharField(max_length=2, choices=PILLAR_ZONES)
    pillar_number = models.IntegerField(null=True, blank=True)
    location_name = models.CharField(max_length=100)
    free_space_available = models.BooleanField(default=True)
    wifi_available = models.BooleanField(default=True)
    seating_capacity = models.IntegerField(default=0)
    power_outlets = models.IntegerField(default=0)
    location_type = models.CharField(max_length=15, choices=LOCATION_TYPES)
    is_active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)
    active_users_count = models.IntegerField(default=0)
    current_crowd_level = models.CharField(max_length=10, choices=CROWD_LEVELS, default='light')
    wifi_status = models.BooleanField(default=True)
    available_seats = models.IntegerField(default=0)

    # Add the custom manager properly
    objects = LocationManager()

    def __str__(self):
        return self.location_name


class LocationShare(models.Model):
    """User location sharing with friends"""
    VISIBILITY_CHOICES = [
        ('all_friends', 'All Friends'),
        ('specific_friends', 'Specific Friends'),
        ('public', 'Public'),
    ]
    
    STATUS_CHOICES = [
        ('studying', 'Studying'),
        ('available', 'Available'),
        ('busy', 'Busy'),
    ]
    
    SHARE_TYPES = [
        ('check_in', 'Check In'),
        ('help_request', 'Help Request'),
        ('study_invite', 'Study Invite'),
    ]

    share_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='location_shares')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='location_shares')
    shared_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='all_friends')
    status_message = models.CharField(max_length=20, choices=STATUS_CHOICES, default='studying')
    share_type = models.CharField(max_length=15, choices=SHARE_TYPES, default='check_in')

    class Meta:
        ordering = ['-shared_at']

    def __str__(self):
        return f"{self.user.username} at {self.location.location_name}"

    def is_expired(self):
        """Check if the location share has expired"""
        from django.utils import timezone
        return timezone.now() > self.expires_at
    
    def time_since_shared(self):
        """Get human readable time since shared"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        diff = now - self.shared_at
        
        if diff.seconds < 60:
            return "Just now"
        elif diff.seconds < 3600:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif diff.days < 1:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"


class LocationShareTarget(models.Model):
    """Specific friend targets for location shares"""
    target_id = models.AutoField(primary_key=True)
    share = models.ForeignKey(LocationShare, on_delete=models.CASCADE, related_name='targets')
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_share_notifications')
    notification_sent = models.BooleanField(default=False)
    notified_at = models.DateTimeField(null=True, blank=True)
    is_seen = models.BooleanField(default=False)

    def __str__(self):
        return f"Target: {self.target_user.username} for {self.share}"


class Friendship(models.Model):
    """Friend relationships between users"""
    FRIENDSHIP_STATUS = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('blocked', 'Blocked'),
    ]

    friendship_id = models.AutoField(primary_key=True)
    user1 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='friendships_initiated')
    user2 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='friendships_received')
    status = models.CharField(max_length=10, choices=FRIENDSHIP_STATUS, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Add the custom manager properly
    objects = FriendshipManager()

    class Meta:
        unique_together = ['user1', 'user2']

    def __str__(self):
        return f"{self.user1.username} -> {self.user2.username} ({self.status})"


class Event(models.Model):
    """Campus events and study groups"""
    EVENT_TYPES = [
        ('study_group', 'Study Group'),
        ('social', 'Social'),
        ('academic', 'Academic'),
        ('sports', 'Sports'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('full', 'Full'),
    ]

    event_id = models.AutoField(primary_key=True)
    organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='organized_events')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=15, choices=EVENT_TYPES)
    event_title = models.CharField(max_length=200)
    event_description = models.TextField(max_length=1000)
    event_start = models.DateTimeField()
    event_end = models.DateTimeField()
    max_participants = models.IntegerField(validators=[MinValueValidator(1)])
    current_participants = models.IntegerField(default=1)  # Organizer is automatically a participant
    participant_user_ids = models.JSONField(default=list)  # Store participant user IDs as JSON array
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    requires_approval = models.BooleanField(default=False)
    
    # NEW FIELDS ADDED:
    is_started = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    invited_user_ids = models.JSONField(default=list)  # Users invited but not yet joined
    is_public = models.BooleanField(default=False)  # Campus-wide visibility

    class Meta:
        ordering = ['event_start']

    def __str__(self):
        return f"{self.event_title} ({self.event_start.date()})"

    def save(self, *args, **kwargs):
        # Add organizer to participants list if not already there
        if self.organizer_id and (not self.participant_user_ids or self.organizer_id not in self.participant_user_ids):
            if not self.participant_user_ids:
                self.participant_user_ids = []
            self.participant_user_ids.append(self.organizer_id)
            self.current_participants = len(self.participant_user_ids)
        super().save(*args, **kwargs)
    
    def time_until_start(self):
        """Get human readable time until event starts"""
        from django.utils import timezone
        from datetime import timedelta
        
        if self.is_started:
            return "ongoing"
            
        now = timezone.now()
        diff = self.event_start - now
        
        if diff.total_seconds() <= 0:
            return "starting now"
        elif diff.total_seconds() < 60:
            return "starting soon"
        elif diff.total_seconds() < 3600:
            minutes = int(diff.total_seconds() // 60)
            return f"in {minutes} minute{'s' if minutes != 1 else ''}"
        elif diff.days < 1:
            hours = int(diff.total_seconds() // 3600)
            return f"in {hours} hour{'s' if hours != 1 else ''}"
        else:
            return f"in {diff.days} day{'s' if diff.days != 1 else ''}"
    
    def get_current_participants(self):
        """Get current participant count"""
        return len(self.participant_user_ids) if self.participant_user_ids else 0
    
    def can_join(self):
        """Check if event has space for more participants"""
        return self.get_current_participants() < self.max_participants
    
    def is_ending_soon(self):
        """Check if event is ending within 30 minutes"""
        from django.utils import timezone
        from datetime import timedelta
        
        if not self.is_started:
            return False
            
        return timezone.now() + timedelta(minutes=30) >= self.event_end


class EventActivity(models.Model):
    """Track event-related activities for the activity feed"""
    ACTIVITY_TYPES = [
        ('created', 'Event Created'),
        ('started', 'Event Started'),
        ('joined', 'Joined Event'),
        ('left', 'Left Event'),
        ('cancelled', 'Event Cancelled'),
        ('ended', 'Event Ended'),
    ]
    
    activity_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='event_activities')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='activities')
    activity_type = models.CharField(max_length=15, choices=ACTIVITY_TYPES)
    created_at = models.DateTimeField(auto_now_add=True)
    is_visible = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} {self.activity_type} {self.event.event_title}"




# Memory Manager - Define BEFORE the Memory model
class MemoryManager(models.Manager):
    def get_visible_memories(self, user):
        """Get memories visible to the user"""
        from django.db.models import Q
        
        # Get user's friends
        friends = Friendship.objects.get_friends(user)
        
        return self.filter(
            Q(visibility='public') |
            Q(visibility='friends', user__in=friends) |
            Q(visibility='friends', user=user) |
            Q(visibility='private', user=user)
        ).select_related('user', 'location').order_by('-creation_date')
    
    def get_user_memories(self, user):
        """Get all memories created by a specific user"""
        return self.filter(user=user, is_archived=False).select_related('location').order_by('-creation_date')
    
    def get_public_memories_for_location(self, location):
        """Get public memories for a specific location"""
        return self.filter(
            location=location,
            visibility='public',
            is_archived=False,
            media_type__in=['image', 'video']
        ).select_related('user').order_by('-creation_date')
    
    def get_featured_memories(self):
        """Get featured memories"""
        return self.filter(
            is_featured=True,
            visibility='public',
            is_archived=False
        ).select_related('user', 'location').order_by('-creation_date')


class Memory(models.Model):
    """User memories at specific locations"""
    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('friends', 'Friends Only'),
        ('private', 'Private'),
    ]
    
    MEDIA_TYPES = [
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('none', 'No Media'),
    ]

    memory_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memories')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='memories')
    creation_date = models.DateTimeField(auto_now_add=True)
    memory_title = models.CharField(max_length=200)
    description = models.TextField(max_length=1000)
    
    # Media handling
    media_file = models.FileField(upload_to='memories/%Y/%m/', blank=True, null=True)
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES, default='none')
    
    # Visibility and archiving
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='friends')
    is_archived = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    
    # Additional data
    tags = models.JSONField(default=list, blank=True)
    year_created = models.IntegerField(null=True, blank=True)
    
    # Social features
    likes_count = models.IntegerField(default=0)
    liked_by_user_ids = models.JSONField(default=list, blank=True)
    view_count = models.IntegerField(default=0)
    
    # Timestamps
    last_modified = models.DateTimeField(auto_now=True)
    
    # Custom manager
    objects = MemoryManager()
    
    class Meta:
        ordering = ['-creation_date']
        indexes = [
            models.Index(fields=['user', '-creation_date']),
            models.Index(fields=['visibility', '-creation_date']),
            models.Index(fields=['location', '-creation_date']),
            models.Index(fields=['is_featured', 'visibility']),
            models.Index(fields=['media_type', 'visibility']),
        ]
        verbose_name = 'Memory'
        verbose_name_plural = 'Memories'

    def save(self, *args, **kwargs):
        """Override save to set year_created automatically"""
        if not self.year_created and self.creation_date:
            self.year_created = self.creation_date.year
        elif not self.year_created:
            from django.utils import timezone
            self.year_created = timezone.now().year
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.memory_title} by {self.user.username}"
    
    def clean(self):
        """Validate model data"""
        from django.core.exceptions import ValidationError
        
        # Validate tags
        if self.tags and not isinstance(self.tags, list):
            raise ValidationError('Tags must be a list')
        
        # Validate liked_by_user_ids
        if self.liked_by_user_ids and not isinstance(self.liked_by_user_ids, list):
            raise ValidationError('Liked by user IDs must be a list')
    
    # Permission methods
    def can_view(self, user):
        """Check if user can view this memory"""
        if not user.is_authenticated:
            return self.visibility == 'public'
            
        if self.visibility == 'public':
            return True
        elif self.visibility == 'private':
            return self.user == user
        elif self.visibility == 'friends':
            if self.user == user:
                return True
            # Check if users are friends
            return Friendship.objects.are_friends(self.user, user)
        return False
    
    def can_edit(self, user):
        """Check if user can edit this memory"""
        return user.is_authenticated and self.user == user
    
    def can_delete(self, user):
        """Check if user can delete this memory"""
        return self.can_edit(user)
    
    # Social interaction methods
    def toggle_like(self, user):
        """Toggle like for this memory"""
        if not user.is_authenticated:
            return False
            
        user_id = user.id
        if user_id in self.liked_by_user_ids:
            self.liked_by_user_ids.remove(user_id)
            self.likes_count = max(0, self.likes_count - 1)
            is_liked = False
        else:
            self.liked_by_user_ids.append(user_id)
            self.likes_count += 1
            is_liked = True
        
        self.save(update_fields=['liked_by_user_ids', 'likes_count'])
        return is_liked
    
    def is_liked_by(self, user):
        """Check if user has liked this memory"""
        return user.is_authenticated and user.id in self.liked_by_user_ids
    
    def increment_view_count(self):
        """Increment view count"""
        self.view_count += 1
        self.save(update_fields=['view_count'])
    
    # Utility properties
    @property
    def has_media(self):
        """Check if memory has media file"""
        return self.media_file and self.media_type != 'none'
    
    @property
    def is_image(self):
        """Check if memory has image"""
        return self.media_type == 'image' and self.media_file
    
    @property
    def is_video(self):
        """Check if memory has video"""
        return self.media_type == 'video' and self.media_file
    
    @property
    def is_audio(self):
        """Check if memory has audio"""
        return self.media_type == 'audio' and self.media_file
    
    @property
    def media_url(self):
        """Get media file URL"""
        return self.media_file.url if self.media_file else None
    
    @property
    def tag_list(self):
        """Get tags as a comma-separated string"""
        return ', '.join(self.tags) if self.tags else ''
    
    def get_absolute_url(self):
        """Get URL for this memory"""
        from django.urls import reverse
        return reverse('memory_detail', kwargs={'memory_id': self.memory_id})
    
    # Time-based methods
    def time_since_created(self):
        """Get human-readable time since creation"""
        from django.utils import timezone
        from django.utils.timesince import timesince
        return timesince(self.creation_date, timezone.now())
    
    def is_recent(self, days=7):
        """Check if memory was created recently"""
        from django.utils import timezone
        from datetime import timedelta
        return self.creation_date >= timezone.now() - timedelta(days=days) 




class LocationReview(models.Model):
    """Location reviews with integrated crowd reporting"""
    CROWD_LEVELS = [
        ('light', 'Light'),
        ('moderate', 'Moderate'),
        ('heavy', 'Heavy'),
    ]
    
    REVIEW_CATEGORIES = [
        ('study_space', 'Study Space'),
        ('wifi_quality', 'WiFi Quality'),
        ('cleanliness', 'Cleanliness'),
        ('noise_level', 'Noise Level'),
        ('general', 'General'),
    ]

    review_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='location_reviews')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='reviews')
    
    # Separate rating fields for different aspects
    wifi_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)], default=5)
    cleanliness_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)], default=5)
    noise_rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)], default=5)
    general_rating = models.FloatField(validators=[MinValueValidator(1.0), MaxValueValidator(10.0)], default=5.0)
    
    # Keep the old rating field for backward compatibility, but make it optional
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)], null=True, blank=True)
    
    review_text = models.TextField(max_length=500, blank=True)
    review_category = models.CharField(max_length=15, choices=REVIEW_CATEGORIES, default='general')
    crowd_level = models.CharField(max_length=10, choices=CROWD_LEVELS)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    helpfulness_score = models.IntegerField(default=0)

    class Meta:
        unique_together = ['user', 'location']  # One review per user per location
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        # Auto-calculate general rating as average of the three components
        self.general_rating = round((self.wifi_rating + self.cleanliness_rating + self.noise_rating) / 3, 1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.location.location_name} ({self.general_rating}/10)"


