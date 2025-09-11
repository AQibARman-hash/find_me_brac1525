from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Avg, Count, Prefetch
from datetime import timedelta
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse
from django.core.files.storage import default_storage
from django.db import models 
import os

from .models import User, Location, LocationShare, Friendship, LocationReview, Event, EventActivity
from .forms import SignUpForm
from .models import Memory
from django.views.decorators.http import require_POST


def home(request):
    """Display the homepage with login/signup"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    signup_form = SignUpForm()
    login_form = AuthenticationForm()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'signup':
            signup_form = SignUpForm(request.POST)
            if signup_form.is_valid():
                user = signup_form.save()
                login(request, user)
                messages.success(request, 'Account created successfully!')
                return redirect('dashboard')
        
        elif action == 'login':
            login_form = AuthenticationForm(request, data=request.POST)
            if login_form.is_valid():
                username = login_form.cleaned_data.get('username')
                password = login_form.cleaned_data.get('password')
                user = authenticate(username=username, password=password)
                if user is not None:
                    login(request, user)
                    messages.success(request, 'Welcome back!')
                    return redirect('dashboard')
            else:
                messages.error(request, 'Invalid username or password.')
    
    return render(request, 'main/index.html', {
        'signup_form': signup_form,
        'login_form': login_form
    })


def update_location_crowd_level(location):
    """Update location's current crowd level based on recent reviews"""
    try:
        recent_reviews = LocationReview.objects.filter(
            location=location,
            created_at__gte=timezone.now() - timedelta(hours=2)
        )
        
        if recent_reviews.exists():
            # Get the most common crowd level from recent reviews
            crowd_counts = {}
            for review in recent_reviews:
                crowd_counts[review.crowd_level] = crowd_counts.get(review.crowd_level, 0) + 1
            
            most_common_crowd = max(crowd_counts.items(), key=lambda x: x[1])[0]
            location.current_crowd_level = most_common_crowd
            location.save(update_fields=['current_crowd_level'])
    except Exception as e:
        print(f"DEBUG - Error updating crowd level: {e}")


@login_required
def dashboard(request):
    """Enhanced dashboard with location sharing, review functionality, and events"""
    
    # Clean up expired shares at the start
    try:
        LocationShare.objects.filter(
            expires_at__lte=timezone.now(),
            is_active=True
        ).update(is_active=False)
    except Exception as e:
        print(f"DEBUG - Error cleaning expired shares: {e}")
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'share_location':
            location_id = request.POST.get('location_id')
            status_message = request.POST.get('status_message', 'studying')
            
            if location_id:
                try:
                    location = Location.objects.get(location_id=location_id)
                    
                    # Deactivate previous location shares for this user
                    LocationShare.objects.filter(
                        user=request.user,
                        is_active=True
                    ).update(is_active=False)
                    
                    # Create new location share
                    LocationShare.objects.create(
                        user=request.user,
                        location=location,
                        expires_at=timezone.now() + timedelta(hours=4),
                        is_active=True,
                        visibility='all_friends',
                        status_message=status_message,
                        share_type='check_in'
                    )
                    
                    # Update location active users count
                    location.active_users_count = LocationShare.objects.filter(
                        location=location,
                        is_active=True,
                        expires_at__gt=timezone.now()
                    ).count()
                    location.save(update_fields=['active_users_count'])
                    
                    messages.success(request, f'Location shared: {location.location_name}')
                except Location.DoesNotExist:
                    messages.error(request, 'Invalid location selected')
                except Exception as e:
                    messages.error(request, f'Error sharing location: {str(e)}')
                    print(f"DEBUG - Location share error: {e}")
        
        elif action == 'stop_sharing':
            try:
                # Get the current active share before stopping it
                current_share = LocationShare.objects.filter(
                    user=request.user,
                    is_active=True,
                    expires_at__gt=timezone.now()
                ).select_related('location').first()
                
                # Stop current location sharing
                LocationShare.objects.filter(
                    user=request.user,
                    is_active=True
                ).update(is_active=False)
                
                # Update location active users count
                if current_share:
                    location = current_share.location
                    location.active_users_count = LocationShare.objects.filter(
                        location=location,
                        is_active=True,
                        expires_at__gt=timezone.now()
                    ).count()
                    location.save(update_fields=['active_users_count'])
                    
                    # Set session variable to prompt for review
                    request.session['review_prompt_location_id'] = current_share.location.location_id
                    request.session['review_prompt_location_name'] = current_share.location.location_name
                
                messages.success(request, 'Location sharing stopped')
            except Exception as e:
                messages.error(request, 'Error stopping location share')
                print(f"DEBUG - Stop sharing error: {e}")
        
        elif action == 'submit_review':
            try:
                location_id = request.POST.get('location_id')
                wifi_rating = request.POST.get('wifi_rating')
                cleanliness_rating = request.POST.get('cleanliness_rating')
                noise_rating = request.POST.get('noise_rating')
                general_rating = request.POST.get('general_rating')
                crowd_level = request.POST.get('crowd_level')
                review_text = request.POST.get('review_text', '').strip()
                
                if not all([location_id, wifi_rating, cleanliness_rating, noise_rating, crowd_level]):
                    messages.error(request, 'Please fill in all required fields')
                    return redirect('dashboard')
                
                # Validate ratings
                try:
                    wifi_rating = int(wifi_rating)
                    cleanliness_rating = int(cleanliness_rating)
                    noise_rating = int(noise_rating)
                    general_rating = float(general_rating)
                    
                    if not all([1 <= wifi_rating <= 10, 1 <= cleanliness_rating <= 10, 
                               1 <= noise_rating <= 10, 1.0 <= general_rating <= 10.0]):
                        messages.error(request, 'Ratings must be between 1 and 10.')
                        return redirect('dashboard')
                except (ValueError, TypeError):
                    messages.error(request, 'Invalid rating values.')
                    return redirect('dashboard')
                
                location = get_object_or_404(Location, location_id=location_id)
                
                # Check if user already reviewed this location
                existing_review = LocationReview.objects.filter(
                    user=request.user,
                    location=location
                ).first()
                
                if existing_review:
                    # Update existing review
                    existing_review.wifi_rating = wifi_rating
                    existing_review.cleanliness_rating = cleanliness_rating
                    existing_review.noise_rating = noise_rating
                    existing_review.general_rating = general_rating
                    existing_review.crowd_level = crowd_level
                    existing_review.review_text = review_text
                    existing_review.created_at = timezone.now()
                    existing_review.save()
                    messages.success(request, f'Review updated for {location.location_name}')
                else:
                    # Create new review
                    LocationReview.objects.create(
                        user=request.user,
                        location=location,
                        wifi_rating=wifi_rating,
                        cleanliness_rating=cleanliness_rating,
                        noise_rating=noise_rating,
                        general_rating=general_rating,
                        crowd_level=crowd_level,
                        review_text=review_text
                    )
                    messages.success(request, f'Review submitted for {location.location_name}')
                
                # Update location crowd level
                update_location_crowd_level(location)
                
                # Clear the review prompt if it exists
                if 'review_prompt_location_id' in request.session:
                    if request.session['review_prompt_location_id'] == location_id:
                        del request.session['review_prompt_location_id']
                        del request.session['review_prompt_location_name']
                        
            except Exception as e:
                messages.error(request, 'Error submitting review')
                print(f"DEBUG - Review submission error: {e}")
        
        elif action == 'dismiss_review_prompt':
            if 'review_prompt_location_id' in request.session:
                del request.session['review_prompt_location_id']
                del request.session['review_prompt_location_name']
        
        # NEW EVENT HANDLERS
        elif action == 'create_event':
            try:
                event_title = request.POST.get('event_title', '').strip()
                event_description = request.POST.get('event_description', '').strip()
                location_id = request.POST.get('location_id')
                event_type = request.POST.get('event_type', 'social')
                max_participants = request.POST.get('max_participants')
                
                # Parse event timing
                hours_from_now = request.POST.get('hours_from_now', 1)
                duration_hours = request.POST.get('duration_hours', 2)
                
                if not all([event_title, location_id, max_participants]):
                    messages.error(request, 'Please fill in all required fields')
                    return redirect('dashboard')
                
                try:
                    hours_from_now = int(hours_from_now)
                    duration_hours = int(duration_hours) 
                    max_participants = int(max_participants)
                    
                    if hours_from_now < 0 or duration_hours < 1 or max_participants < 1:
                        raise ValueError("Invalid values")
                        
                except (ValueError, TypeError):
                    messages.error(request, 'Please enter valid numbers for timing and participants')
                    return redirect('dashboard')
                
                location = get_object_or_404(Location, location_id=location_id)
                
                # Calculate event times
                event_start = timezone.now() + timedelta(hours=hours_from_now)
                event_end = event_start + timedelta(hours=duration_hours)
                
                # Create event
                event = Event.objects.create(
                    organizer=request.user,
                    location=location,
                    event_type=event_type,
                    event_title=event_title,
                    event_description=event_description,
                    event_start=event_start,
                    event_end=event_end,
                    max_participants=max_participants,
                    current_participants=1,
                    participant_user_ids=[request.user.id]
                )
                
                # Create activity record
                EventActivity.objects.create(
                    user=request.user,
                    event=event,
                    activity_type='created'
                )
                
                messages.success(request, f'Event "{event_title}" created successfully!')
                
            except Exception as e:
                messages.error(request, 'Error creating event')
                print(f"DEBUG - Event creation error: {e}")
        
        elif action == 'start_event':
            try:
                event_id = request.POST.get('event_id')
                event = get_object_or_404(Event, event_id=event_id, organizer=request.user)
                
                if event.is_started:
                    messages.info(request, 'Event is already started')
                else:
                    event.is_started = True
                    event.started_at = timezone.now()
                    event.save()
                    
                    # Create activity record
                    EventActivity.objects.create(
                        user=request.user,
                        event=event,
                        activity_type='started'
                    )
                    
                    messages.success(request, f'Event "{event.event_title}" started!')
                
            except Exception as e:
                messages.error(request, 'Error starting event')
                print(f"DEBUG - Event start error: {e}")
        
        elif action == 'join_event':
            try:
                event_id = request.POST.get('event_id')
                event = get_object_or_404(Event, event_id=event_id)
                
                if request.user.id in event.participant_user_ids:
                    messages.info(request, 'You are already participating in this event')
                elif not event.can_join():
                    messages.error(request, 'Event is full')
                else:
                    # Add user to participants
                    event.participant_user_ids.append(request.user.id)
                    event.current_participants = len(event.participant_user_ids)
                    event.save()
                    
                    # Create activity record
                    EventActivity.objects.create(
                        user=request.user,
                        event=event,
                        activity_type='joined'
                    )
                    
                    messages.success(request, f'You joined "{event.event_title}"!')
                
            except Exception as e:
                messages.error(request, 'Error joining event')
                print(f"DEBUG - Event join error: {e}")
        
        elif action == 'leave_event':
            try:
                event_id = request.POST.get('event_id')
                event = get_object_or_404(Event, event_id=event_id)
                
                if request.user.id not in event.participant_user_ids:
                    messages.info(request, 'You are not participating in this event')
                elif event.organizer == request.user:
                    messages.error(request, 'Event organizer cannot leave. Cancel the event instead.')
                else:
                    # Remove user from participants
                    event.participant_user_ids.remove(request.user.id)
                    event.current_participants = len(event.participant_user_ids)
                    event.save()
                    
                    # Create activity record
                    EventActivity.objects.create(
                        user=request.user,
                        event=event,
                        activity_type='left'
                    )
                    
                    messages.success(request, f'You left "{event.event_title}"')
                
            except Exception as e:
                messages.error(request, 'Error leaving event')
                print(f"DEBUG - Event leave error: {e}")
        
        elif action == 'cancel_event':
            try:
                event_id = request.POST.get('event_id')
                event = get_object_or_404(Event, event_id=event_id, organizer=request.user)
                
                # Create activity record before canceling
                EventActivity.objects.create(
                    user=request.user,
                    event=event,
                    activity_type='cancelled'
                )
                
                event.status = 'cancelled'
                event.save()
                
                messages.success(request, f'Event "{event.event_title}" cancelled')
                
            except Exception as e:
                messages.error(request, 'Error cancelling event')
                print(f"DEBUG - Event cancel error: {e}")
        
        elif action == 'logout':
            logout(request)
            messages.success(request, 'You have been logged out successfully.')
            return redirect('home')
        
        return redirect('dashboard')
    
    # Fetch data with proper error handling
    try:
        locations = Location.objects.filter(is_active=True).order_by('location_name')
        print(f"DEBUG - Found {locations.count()} locations")
    except Exception as e:
        print(f"DEBUG - Error fetching locations: {e}")
        locations = Location.objects.none()
        messages.error(request, 'Error loading locations.')
    
    try:
        # Get friends using existing manager
        friends = Friendship.objects.get_friends(request.user)
        print(f"DEBUG - Found {len(friends)} friends")
        
        # Get recent location shares from friends (last 24 hours)
        recent_cutoff = timezone.now() - timedelta(hours=24)
        
        friends_recent_shares = LocationShare.objects.select_related(
            'user', 'location'
        ).filter(
            user__in=friends,
            is_active=True,
            expires_at__gt=timezone.now(),
            shared_at__gte=recent_cutoff
        ).order_by('-shared_at')[:20]
        
        # Get recent events from friends (including user's own events)
        friends_and_user = list(friends) + [request.user]
        recent_events = Event.objects.select_related(
            'organizer', 'location'
        ).filter(
            organizer__in=friends_and_user,
            status='active',
            event_start__gte=timezone.now() - timedelta(hours=2)  # Show recent and upcoming
        ).order_by('event_start')
        
        # Combine and sort activities by time (most recent first)
        combined_activities = []
        
        # Add location shares
        for share in friends_recent_shares:
            combined_activities.append({
                'type': 'location_share',
                'user': share.user,
                'location': share.location,
                'timestamp': share.shared_at,
                'status_message': share.status_message,
                'time_display': share.time_since_shared(),
                'data': share
            })
        
        # Add events
        for event in recent_events:
            combined_activities.append({
                'type': 'event',
                'user': event.organizer,
                'location': event.location,
                'timestamp': event.created_at,
                'time_display': event.time_until_start(),
                'data': event
            })
        
        # Sort combined activities by timestamp (newest first)
        combined_activities.sort(key=lambda x: x['timestamp'], reverse=True)
        combined_activities = combined_activities[:20]  # Limit to 20 items
        
        print(f"DEBUG - Found {friends_recent_shares.count()} recent friend shares")
        
    except Exception as e:
        print(f"DEBUG - Error fetching friend locations: {e}")
        combined_activities = []
        friends = []
    
    try:
        # Get current user's active location share
        current_share = LocationShare.objects.filter(
            user=request.user,
            is_active=True,
            expires_at__gt=timezone.now()
        ).select_related('location').first()
    except Exception as e:
        print(f"DEBUG - Error fetching current share: {e}")
        current_share = None
    
    # Get user's events
    try:
        user_events = Event.objects.filter(
            organizer=request.user,
            status='active'
        ).order_by('event_start')[:10]
        
        user_upcoming_events = user_events.filter(
            event_start__gt=timezone.now()
        )
        
        user_ongoing_events = user_events.filter(
            is_started=True,
            event_end__gt=timezone.now()
        )
        
    except Exception as e:
        print(f"DEBUG - Error fetching user events: {e}")
        user_events = Event.objects.none()
        user_upcoming_events = Event.objects.none()
        user_ongoing_events = Event.objects.none()
    
    # Get review-related data
    try:
        # Get all recent reviews (not just from friends)
        recent_reviews = LocationReview.objects.select_related(
            'user', 'location'
        ).order_by('-created_at')[:15]
        
        # Get user's review statistics
        user_reviews = LocationReview.objects.filter(user=request.user)
        user_review_count = user_reviews.count()
        user_avg_rating = user_reviews.aggregate(Avg('rating'))['rating__avg'] or 0
        
    except Exception as e:
        print(f"DEBUG - Error fetching review data: {e}")
        recent_reviews = LocationReview.objects.none()
        user_review_count = 0
        user_avg_rating = 0
    
    # Calculate statistics
    try:
        total_friends = len(friends)
        friends_currently_sharing = LocationShare.objects.filter(
            user__in=friends,
            is_active=True,
            expires_at__gt=timezone.now()
        ).count()
        
    except Exception as e:
        print(f"DEBUG - Error calculating statistics: {e}")
        total_friends = 0
        friends_currently_sharing = 0
    
    # Check for review prompt from session
    review_prompt_location_id = request.session.get('review_prompt_location_id')
    review_prompt_location_name = request.session.get('review_prompt_location_name')
    
    context = {
        # User and location data
        'user': request.user,
        'current_share': current_share,
        'locations': locations,
        
        # Friend activity data
        'combined_activities': combined_activities,
        'total_friends': total_friends,
        'friends_currently_sharing': friends_currently_sharing,
        
        # Event-related context
        'user_events': user_events,
        'user_upcoming_events': user_upcoming_events,
        'user_ongoing_events': user_ongoing_events,
        'event_types': Event.EVENT_TYPES,
        
        # Review data
        'recent_reviews': recent_reviews,
        'user_review_count': user_review_count,
        'user_avg_rating': round(user_avg_rating, 1) if user_avg_rating else 0,
        
        # Review prompt data
        'review_prompt_location_id': review_prompt_location_id,
        'review_prompt_location_name': review_prompt_location_name,
        
        # Form choices for dropdowns
        'review_categories': LocationReview.REVIEW_CATEGORIES,
        'crowd_levels': LocationReview.CROWD_LEVELS,
    }
    
    return render(request, 'main/dashboard.html', context)


@login_required
def search_users(request):
    """Search for users to add as friends"""
    query = request.GET.get('q', '')
    
    # Get users who are already friends
    existing_friends = Friendship.objects.filter(
        Q(user1=request.user, status='accepted') | Q(user2=request.user, status='accepted')
    ).values_list('user1_id', 'user2_id')
    
    # Flatten the list of friend IDs
    friend_ids = set()
    for user1_id, user2_id in existing_friends:
        friend_ids.add(user1_id if user1_id != request.user.id else user2_id)
    
    # Get users with pending friend requests
    pending_requests = Friendship.objects.filter(
        Q(user1=request.user, status='pending') | Q(user2=request.user, status='pending')
    ).values_list('user1_id', 'user2_id')
    
    # Flatten the list of pending request IDs
    pending_ids = set()
    for user1_id, user2_id in pending_requests:
        pending_ids.add(user1_id if user1_id != request.user.id else user2_id)
    
    if query:
        # Filter users based on search query
        users = User.objects.filter(
            Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query)
        ).exclude(id=request.user.id).exclude(id__in=friend_ids)[:10]
    else:
        # Show all users when no search query (excluding current user and existing friends)
        users = User.objects.exclude(id=request.user.id).exclude(id__in=friend_ids)[:20]
    
    # Add status information to each user
    users_with_status = []
    for user in users:
        user_status = 'can_add'  # Default status
        if user.id in pending_ids:
            # Check if current user sent the request or received it
            sent_request = Friendship.objects.filter(
                user1=request.user, user2=user, status='pending'
            ).exists()
            received_request = Friendship.objects.filter(
                user1=user, user2=request.user, status='pending'
            ).exists()
            
            if sent_request:
                user_status = 'request_sent'
            elif received_request:
                user_status = 'request_received'
        
        users_with_status.append({
            'user': user,
            'status': user_status
        })
    
    return render(request, 'main/search_users.html', {
        'users_with_status': users_with_status,
        'query': query
    })


@login_required
def send_friend_request(request, user_id):
    """Send a friend request"""
    if request.method == 'POST':
        try:
            friend = get_object_or_404(User, id=user_id)
            
            # Check if they're already friends or request exists
            existing_friendship = Friendship.objects.filter(
                Q(user1=request.user, user2=friend) | Q(user1=friend, user2=request.user)
            ).first()
            
            if existing_friendship:
                if existing_friendship.status == 'accepted':
                    messages.info(request, f'You are already friends with {friend.username}')
                elif existing_friendship.status == 'pending':
                    messages.info(request, f'Friend request already sent to {friend.username}')
                else:
                    messages.error(request, 'Cannot send friend request')
            else:
                # Create new friend request
                Friendship.objects.create(
                    user1=request.user,
                    user2=friend,
                    status='pending'
                )
                messages.success(request, f'Friend request sent to {friend.username}!')
                
        except Exception as e:
            messages.error(request, 'Error sending friend request')
            print(f"DEBUG - Friend request error: {e}")
    
    return redirect('search_users')


@login_required
def friend_requests(request):
    """View and manage friend requests"""
    # Pending requests received by current user
    received_requests = Friendship.objects.filter(
        user2=request.user,
        status='pending'
    ).select_related('user1')
    
    # Pending requests sent by current user
    sent_requests = Friendship.objects.filter(
        user1=request.user,
        status='pending'
    ).select_related('user2')
    
    return render(request, 'main/friend_requests.html', {
        'received_requests': received_requests,
        'sent_requests': sent_requests
    })


@login_required
def respond_friend_request(request, friendship_id):
    """Accept or reject a friend request"""
    if request.method == 'POST':
        try:
            friendship = get_object_or_404(
                Friendship, 
                friendship_id=friendship_id, 
                user2=request.user,  # Only the recipient can respond
                status='pending'
            )
            
            action = request.POST.get('action')
            
            if action == 'accept':
                friendship.status = 'accepted'
                friendship.accepted_at = timezone.now()
                friendship.save()
                messages.success(request, f'You are now friends with {friendship.user1.username}!')
                
            elif action == 'reject':
                friendship.delete()  # Or set status to 'rejected' if you want to keep record
                messages.info(request, 'Friend request declined')
                
        except Exception as e:
            messages.error(request, 'Error processing friend request')
            print(f"DEBUG - Friend request response error: {e}")
    
    return redirect('friend_requests')


@login_required
def friends_list(request):
    """View all friends"""
    friends = Friendship.objects.get_friends(request.user)
    
    return render(request, 'main/friendlists.html', {
        'friends': friends
    })


@login_required
def discover_locations(request):
    """Discover locations with their public photos and review statistics"""
    
    # Get locations with their review statistics
    locations_with_stats = Location.objects.filter(
        is_active=True
    ).annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews'),
        recent_review_count=Count('reviews', filter=Q(
            reviews__created_at__gte=timezone.now() - timedelta(days=7)
        )),
        memory_count=Count('memories', filter=Q(
            memories__visibility='public',
            memories__is_archived=False
        ))
    ).prefetch_related(
        # Get public memories with images for each location - NO SLICE HERE
        Prefetch('memories', 
            queryset=Memory.objects.filter(
                visibility='public',
                is_archived=False,
                media_type__in=['image', 'video']
            ).select_related('user').order_by('-creation_date')  # Removed [:6]
        )
    ).order_by('-memory_count', '-avg_rating', '-review_count')
    
    # Filter options
    category_filter = request.GET.get('category')
    min_rating = request.GET.get('min_rating')
    has_photos_only = request.GET.get('has_photos') == 'true'
    
    if category_filter:
        locations_with_stats = locations_with_stats.filter(
            reviews__review_category=category_filter
        ).distinct()
    
    if min_rating:
        try:
            locations_with_stats = locations_with_stats.filter(
                avg_rating__gte=float(min_rating)
            )
        except (ValueError, TypeError):
            pass
    
    if has_photos_only:
        locations_with_stats = locations_with_stats.filter(memory_count__gt=0)
    
    # Get the total count BEFORE slicing
    total_locations = locations_with_stats.count()
    
    # Get recent public memories across all locations for the "Recent Memories" section
    recent_public_memories = Memory.objects.filter(
        visibility='public',
        is_archived=False,
        media_type__in=['image', 'video']
    ).select_related('user', 'location').order_by('-creation_date')[:20]
    
    context = {
        'locations': locations_with_stats[:30],  # Top 30 locations
        'recent_memories': recent_public_memories,
        'review_categories': LocationReview.REVIEW_CATEGORIES,
        'current_category': category_filter,
        'current_min_rating': min_rating,
        'has_photos_only': has_photos_only,
        'total_locations': total_locations
    }
    
    return render(request, 'main/discover_locations.html', context)


@login_required
def location_reviews(request, location_id=None):
    """View and manage location reviews"""
    
    if location_id:
        location = get_object_or_404(Location, location_id=location_id, is_active=True)
        reviews = LocationReview.objects.filter(location=location).select_related('user').order_by('-created_at')
        
        # Get review statistics for this location
        review_stats = reviews.aggregate(
            avg_rating=Avg('rating'),
            total_reviews=Count('review_id')
        )
        
        # Get crowd level distribution
        crowd_distribution = reviews.values('crowd_level').annotate(
            count=Count('crowd_level')
        ).order_by('crowd_level')
        
        context = {
            'location': location,
            'reviews': reviews[:20],  # Limit to 20 reviews
            'review_stats': review_stats,
            'crowd_distribution': crowd_distribution,
        }
        
        return render(request, 'main/location_reviews.html', context)
    
    else:
        # Show all recent reviews
        friends = Friendship.objects.get_friends(request.user)
        recent_reviews = LocationReview.objects.select_related(
            'user', 'location'
        ).filter(
            user__in=friends
        ).order_by('-created_at')[:50]
        
        return render(request, 'main/all_reviews.html', {
            'recent_reviews': recent_reviews
        })


@login_required
def my_reviews(request):
    """View user's own reviews"""
    user_reviews = LocationReview.objects.filter(
        user=request.user
    ).select_related('location').order_by('-created_at')
    
    # Get user's review statistics
    review_stats = user_reviews.aggregate(
        avg_rating=Avg('rating'),
        total_reviews=Count('review_id')
    )
    
    # Get category breakdown
    category_breakdown = user_reviews.values('review_category').annotate(
        count=Count('review_category')
    ).order_by('-count')
    
    return render(request, 'main/my_reviews.html', {
        'user_reviews': user_reviews,
        'review_stats': review_stats,
        'category_breakdown': category_breakdown,
    })      


@login_required
def memories_feed(request):
    """Display all memories visible to the user in Facebook-style feed"""
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create_memory':
            try:
                memory_title = request.POST.get('memory_title', '').strip()
                description = request.POST.get('description', '').strip()
                location_id = request.POST.get('location_id')
                visibility = request.POST.get('visibility', 'friends')
                tags = request.POST.get('tags', '').strip()
                media_file = request.FILES.get('media_file')
                
                if not all([memory_title, description, location_id]):
                    messages.error(request, 'Please fill in all required fields')
                    return redirect('memories_feed')
                
                location = get_object_or_404(Location, location_id=location_id, is_active=True)
                
                # Process tags
                tag_list = [tag.strip() for tag in tags.split(',') if tag.strip()] if tags else []
                
                # Determine media type
                media_type = 'none'
                if media_file:
                    file_extension = os.path.splitext(media_file.name)[1].lower()
                    if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                        media_type = 'image'
                    elif file_extension in ['.mp4', '.avi', '.mov', '.wmv']:
                        media_type = 'video'
                    elif file_extension in ['.mp3', '.wav', '.ogg']:
                        media_type = 'audio'
                
                # Create memory
                memory = Memory.objects.create(
                    user=request.user,
                    location=location,
                    memory_title=memory_title,
                    description=description,
                    visibility=visibility,
                    tags=tag_list,
                    media_file=media_file,
                    media_type=media_type
                )
                
                messages.success(request, f'Memory "{memory_title}" created successfully!')
                
            except Exception as e:
                messages.error(request, 'Error creating memory')
                print(f"DEBUG - Memory creation error: {e}")
        
        elif action == 'toggle_like':
            try:
                memory_id = request.POST.get('memory_id')
                memory = get_object_or_404(Memory, memory_id=memory_id)
                
                if memory.can_view(request.user):
                    is_liked = memory.toggle_like(request.user)
                    
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'liked': is_liked,
                            'likes_count': memory.likes_count
                        })
                    else:
                        messages.success(request, 'Memory liked!' if is_liked else 'Like removed')
                else:
                    messages.error(request, 'You cannot like this memory')
                    
            except Exception as e:
                messages.error(request, 'Error processing like')
                print(f"DEBUG - Like toggle error: {e}")
        
        return redirect('memories_feed')
    
    # Get memories visible to the user
    try:
        memories = Memory.objects.get_visible_memories(request.user).filter(is_archived=False)
        
        # Pagination
        paginator = Paginator(memories, 10)  # Show 10 memories per page
        page = request.GET.get('page', 1)
        
        try:
            memories_page = paginator.page(page)
        except PageNotAnInteger:
            memories_page = paginator.page(1)
        except EmptyPage:
            memories_page = paginator.page(paginator.num_pages)
        
        # Add can_edit flag to each memory
        for memory in memories_page:
            memory.user_can_edit = memory.can_edit(request.user)
            memory.user_has_liked = request.user.id in memory.liked_by_user_ids
            
    except Exception as e:
        print(f"DEBUG - Error fetching memories: {e}")
        memories_page = []
        messages.error(request, 'Error loading memories.')
    
    # Get locations for the create form
    try:
        locations = Location.objects.filter(is_active=True).order_by('location_name')
    except Exception as e:
        print(f"DEBUG - Error fetching locations: {e}")
        locations = Location.objects.none()
    
    context = {
        'memories_page': memories_page,
        'locations': locations,
        'memory_visibility_choices': Memory.VISIBILITY_CHOICES,
        'page_title': 'Memories Feed'
    }
    
    return render(request, 'main/memories_feed.html', context)


@login_required
def my_memories(request):
    """Display user's own memories"""
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'delete_memory':
            try:
                memory_id = request.POST.get('memory_id')
                memory = get_object_or_404(Memory, memory_id=memory_id, user=request.user)
                
                # Delete associated media file if exists
                if memory.media_file:
                    try:
                        default_storage.delete(memory.media_file.path)
                    except:
                        pass  # File might not exist
                
                memory_title = memory.memory_title
                memory.delete()
                
                messages.success(request, f'Memory "{memory_title}" deleted successfully!')
                
            except Exception as e:
                messages.error(request, 'Error deleting memory')
                print(f"DEBUG - Memory deletion error: {e}")
        
        elif action == 'archive_memory':
            try:
                memory_id = request.POST.get('memory_id')
                memory = get_object_or_404(Memory, memory_id=memory_id, user=request.user)
                
                memory.is_archived = not memory.is_archived
                memory.save(update_fields=['is_archived'])
                
                action_word = 'archived' if memory.is_archived else 'restored'
                messages.success(request, f'Memory "{memory.memory_title}" {action_word}!')
                
            except Exception as e:
                messages.error(request, 'Error archiving memory')
                print(f"DEBUG - Memory archive error: {e}")
        
        elif action == 'update_visibility':
            try:
                memory_id = request.POST.get('memory_id')
                new_visibility = request.POST.get('visibility')
                memory = get_object_or_404(Memory, memory_id=memory_id, user=request.user)
                
                if new_visibility in dict(Memory.VISIBILITY_CHOICES):
                    memory.visibility = new_visibility
                    memory.save(update_fields=['visibility'])
                    
                    messages.success(request, f'Memory visibility updated to {memory.get_visibility_display()}!')
                else:
                    messages.error(request, 'Invalid visibility option')
                    
            except Exception as e:
                messages.error(request, 'Error updating visibility')
                print(f"DEBUG - Visibility update error: {e}")
        
        return redirect('my_memories')
    
    # Get user's memories
    try:
        # Include archived memories with filter option
        show_archived = request.GET.get('archived') == 'true'
        
        if show_archived:
            memories = Memory.objects.filter(user=request.user).select_related('location').order_by('-creation_date')
        else:
            memories = Memory.objects.get_user_memories(request.user)
        
        # Pagination
        paginator = Paginator(memories, 12)  # Show 12 memories per page
        page = request.GET.get('page', 1)
        
        try:
            memories_page = paginator.page(page)
        except PageNotAnInteger:
            memories_page = paginator.page(1)
        except EmptyPage:
            memories_page = paginator.page(paginator.num_pages)
        
        # Add user_has_liked flag
        for memory in memories_page:
            memory.user_has_liked = request.user.id in memory.liked_by_user_ids
            
    except Exception as e:
        print(f"DEBUG - Error fetching user memories: {e}")
        memories_page = []
        messages.error(request, 'Error loading your memories.')
    
    # Get memory statistics
    try:
        total_memories = Memory.objects.filter(user=request.user).count()
        total_likes = Memory.objects.filter(user=request.user).aggregate(
            total_likes=models.Sum('likes_count')
        )['total_likes'] or 0
        archived_count = Memory.objects.filter(user=request.user, is_archived=True).count()
        
        memory_stats = {
            'total_memories': total_memories,
            'total_likes': total_likes,
            'archived_count': archived_count,
            'active_count': total_memories - archived_count
        }
    except Exception as e:
        print(f"DEBUG - Error calculating memory stats: {e}")
        memory_stats = {
            'total_memories': 0,
            'total_likes': 0,
            'archived_count': 0,
            'active_count': 0
        }
    
    context = {
        'memories_page': memories_page,
        'memory_stats': memory_stats,
        'show_archived': show_archived,
        'memory_visibility_choices': Memory.VISIBILITY_CHOICES,
        'page_title': 'My Memories'
    }
    
    return render(request, 'main/my_memories.html', context)


@login_required
@require_POST
def memory_detail_ajax(request):
    """AJAX endpoint for memory details"""
    try:
        memory_id = request.POST.get('memory_id')
        memory = get_object_or_404(Memory, memory_id=memory_id)
        
        if not memory.can_view(request.user):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Increment view count
        memory.view_count += 1
        memory.save(update_fields=['view_count'])
        
        memory_data = {
            'id': memory.memory_id,
            'title': memory.memory_title,
            'description': memory.description,
            'user': memory.user.get_full_name() or memory.user.username,
            'location': memory.location.location_name,
            'created': memory.creation_date.strftime('%B %d, %Y at %I:%M %p'),
            'likes_count': memory.likes_count,
            'view_count': memory.view_count,
            'tags': memory.tags,
            'media_type': memory.media_type,
            'media_url': memory.media_file.url if memory.media_file else None,
            'visibility': memory.get_visibility_display(),
            'user_has_liked': request.user.id in memory.liked_by_user_ids,
            'can_edit': memory.can_edit(request.user)
        }
        
        return JsonResponse(memory_data)
        
    except Exception as e:
        print(f"DEBUG - Memory detail AJAX error: {e}")
        return JsonResponse({'error': 'Error loading memory details'}, status=500) 


