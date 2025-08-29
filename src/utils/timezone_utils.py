import pytz
from datetime import datetime, date
from typing import Optional

def get_user_timezone(timezone_str: str = "America/Los_Angeles") -> pytz.timezone:
    """Get a timezone object from string, with fallback to PST."""
    try:
        return pytz.timezone(timezone_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.timezone("America/Los_Angeles")

def utc_to_user_timezone(utc_datetime: datetime, user_timezone: str = "America/Los_Angeles") -> datetime:
    """Convert UTC datetime to user's timezone."""
    if utc_datetime.tzinfo is None:
        # Assume UTC if no timezone info
        utc_datetime = pytz.UTC.localize(utc_datetime)
    
    user_tz = get_user_timezone(user_timezone)
    return utc_datetime.astimezone(user_tz)

def user_timezone_to_utc(user_datetime: datetime, user_timezone: str = "America/Los_Angeles") -> datetime:
    """Convert user timezone datetime to UTC."""
    user_tz = get_user_timezone(user_timezone)
    
    if user_datetime.tzinfo is None:
        # Localize to user timezone if no timezone info
        user_datetime = user_tz.localize(user_datetime)
    
    return user_datetime.astimezone(pytz.UTC)

def get_today_in_user_timezone(user_timezone: str = "America/Los_Angeles") -> date:
    """Get today's date in user's timezone."""
    user_tz = get_user_timezone(user_timezone)
    now = datetime.now(user_tz)
    return now.date()

def format_datetime_for_display(datetime_obj: datetime, user_timezone: str = "America/Los_Angeles", 
                               format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format datetime for display in user's timezone."""
    if datetime_obj.tzinfo is None:
        # Assume UTC if no timezone info
        datetime_obj = pytz.UTC.localize(datetime_obj)
    
    user_tz = get_user_timezone(user_timezone)
    user_datetime = datetime_obj.astimezone(user_tz)
    return user_datetime.strftime(format_str)

def format_date_for_display(date_obj: date, user_timezone: str = "America/Los_Angeles") -> str:
    """Format date for display in user's timezone."""
    return date_obj.strftime("%Y-%m-%d") 