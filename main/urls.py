# main/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Existing URLs
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('search-users/', views.search_users, name='search_users'),
    path('send-friend-request/<int:user_id>/', views.send_friend_request, name='send_friend_request'),
    path('friend-requests/', views.friend_requests, name='friend_requests'),
    path('respond-friend-request/<int:friendship_id>/', views.respond_friend_request, name='respond_friend_request'),
    path('friends/', views.friends_list, name='friends_list'),
    
    # NEW: Review-related URLs
    path('reviews/', views.location_reviews, name='all_reviews'),
    path('reviews/location/<int:location_id>/', views.location_reviews, name='location_reviews'),
    path('reviews/my/', views.my_reviews, name='my_reviews'),
    path('discover-locations/', views.discover_locations, name='discover_locations'),


    # main/urls.py (add these paths)

    path('memories/', views.memories_feed, name='memories_feed'),
    path('memories/my/', views.my_memories, name='my_memories'),
    path('memories/detail/', views.memory_detail_ajax, name='memory_detail_ajax'),
    # In your main/urls.py
    path('discover/', views.discover_locations, name='discover_locations'),

]  

