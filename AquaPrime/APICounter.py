import datetime


class APICounter:
    """
    APICounter is a Python class that implements a simple counter system to track and limit the number of requests
    allowed per day for each user.

    Attributes:
        max_requests_per_day (int): The maximum number of requests allowed per day.
        requests (dict): A dictionary that stores the request count for each user, keyed by user ID.
    Methods:
        __init__(self, max_requests_per_day):
            Initializes a new instance of the APICounter class with the specified maximum limit of requests per day.

        check_limit(self, user_id):
            Checks if the user has exceeded the maximum number of requests allowed per day based on the current date.
            If the user has not exceeded the limit, updates the request count for the user and returns True. If the user
            has exceeded the limit, returns False.

    Usage:
        # Create an instance of APICounter with a maximum limit of 5 requests per day
        counter = APICounter(5)

        # Example usage in your API endpoint
        user_id = "user123"
        if counter.check_limit(user_id):
            # Process the API request for the user
            print("API request processed.")
        else:
            print("API request limit exceeded.")
    """
    def __init__(self, max_requests_per_day):
        """
        Initializes a new instance of the APICounter class with the specified maximum limit of requests per day.

        Args:
            max_requests_per_day (int): The maximum number of requests allowed per day.
        """
        self.max_requests_per_day = int(max_requests_per_day)
        self.requests = {}

    def check_limit(self, user_id):
        """
        Checks if the user has exceeded the maximum number of requests allowed per day based on the current date.
        If the user has not exceeded the limit, updates the request count for the user and returns True. If the user
        has exceeded the limit, returns False.

        Args:
            user_id (str): The ID of the user making the API request.

        Returns:
            bool: True if the user has not exceeded the request limit, False otherwise.
        """
        today = datetime.date.today()
        if user_id not in self.requests:
            self.requests[user_id] = {"date": today, "count": 0}
        elif self.requests[user_id]["date"] != today:
            self.requests[user_id]["date"] = today
            self.requests[user_id]["count"] = 0

        if self.requests[user_id]["count"] < self.max_requests_per_day:
            self.requests[user_id]["count"] += 1
            return True
        else:
            return False