import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class RouterConnectionError(Exception):
    """Raised when RouterOS connection fails."""
    pass


class HotspotUserError(Exception):
    """Raised when hotspot user operation fails."""
    pass


class RouterConnection(ABC):
    """Abstract base class for router connections."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Test connection to router."""
        pass

    @abstractmethod
    def create_hotspot_user(
        self,
        username: str,
        password: str,
        profile: str = "default"
    ) -> Dict[str, Any]:
        """Create a hotspot user. Returns dict with status and user_id."""
        pass

    @abstractmethod
    def remove_hotspot_user(self, username: str) -> bool:
        """Remove a hotspot user. Returns True if successful."""
        pass

    @abstractmethod
    def get_hotspot_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get hotspot user details. Returns dict or None if not found."""
        pass


class MockRouterConnection(RouterConnection):
    """Mock RouterOS connection for testing without a real router."""

    def __init__(self, host: str = "mock", username: str = "mock", password: str = "mock"):
        self.host = host
        self.username = username
        self.password = password
        self.users: Dict[str, Dict[str, str]] = {}
        logger.info(f"MockRouterConnection initialized for {host}")

    def test_connection(self) -> bool:
        """Mock connection test always succeeds."""
        logger.info(f"Mock connection test to {self.host}: SUCCESS")
        return True

    def create_hotspot_user(
        self,
        username: str,
        password: str,
        profile: str = "default"
    ) -> Dict[str, Any]:
        """Mock hotspot user creation."""
        self.users[username] = {
            "username": username,
            "password": password,
            "profile": profile,
        }
        logger.info(f"Mock hotspot user created: {username} (profile: {profile})")
        return {
            "success": True,
            "user_id": f"mock-{username}",
            "username": username,
            "profile": profile,
        }

    def remove_hotspot_user(self, username: str) -> bool:
        """Mock hotspot user removal."""
        if username in self.users:
            del self.users[username]
            logger.info(f"Mock hotspot user removed: {username}")
            return True
        logger.warning(f"Mock hotspot user not found: {username}")
        return False

    def get_hotspot_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Mock get hotspot user."""
        if username in self.users:
            return self.users[username]
        return None


class RealRouterConnection(RouterConnection):
    """Real RouterOS connection using routeros-api library."""

    def __init__(self, host: str, username: str, password: str, use_ssl: bool = False):
        self.host = host
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.api = None
        self._connect()

    def _connect(self):
        """Establish connection to RouterOS."""
        try:
            import routeros_api

            self.connection = routeros_api.RouterOsApiPool(
                host=self.host,
                username=self.username,
                password=self.password,
                plaintext_login=not self.use_ssl,
                use_ssl=self.use_ssl,
            )
            self.api = self.connection.get_api()
            logger.info(f"Connected to RouterOS at {self.host}")
        except ImportError:
            raise RouterConnectionError(
                "routeros-api not installed. Install with: pip install routeros-api"
            )
        except Exception as e:
            raise RouterConnectionError(f"Failed to connect to {self.host}: {str(e)}")

    def test_connection(self) -> bool:
        """Test connection to RouterOS."""
        try:
            # Try to get identity - lightweight test
            resource = self.api.get_resource("/system/identity")
            result = resource.get()
            logger.info(f"RouterOS connection test successful: {result}")
            return True
        except Exception as e:
            logger.error(f"RouterOS connection test failed: {str(e)}")
            return False

    def create_hotspot_user(
        self,
        username: str,
        password: str,
        profile: str = "default"
    ) -> Dict[str, Any]:
        """Create a hotspot user on RouterOS."""
        try:
            users = self.api.get_resource("/ip/hotspot/user")
            user_id = users.add(
                name=username,
                password=password,
                profile=profile,
            )
            logger.info(f"Hotspot user created: {username} (ID: {user_id}, profile: {profile})")
            return {
                "success": True,
                "user_id": user_id,
                "username": username,
                "profile": profile,
            }
        except Exception as e:
            logger.error(f"Failed to create hotspot user {username}: {str(e)}")
            raise HotspotUserError(f"Failed to create user: {str(e)}")

    def remove_hotspot_user(self, username: str) -> bool:
        """Remove a hotspot user from RouterOS."""
        try:
            users = self.api.get_resource("/ip/hotspot/user")
            # Query for user by name
            user_list = users.get(name=username)
            if user_list:
                user_id = user_list[0]["id"]
                users.remove(id=user_id)
                logger.info(f"Hotspot user removed: {username} (ID: {user_id})")
                return True
            else:
                logger.warning(f"Hotspot user not found for removal: {username}")
                return False
        except Exception as e:
            logger.error(f"Failed to remove hotspot user {username}: {str(e)}")
            return False

    def get_hotspot_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get hotspot user details from RouterOS."""
        try:
            users = self.api.get_resource("/ip/hotspot/user")
            user_list = users.get(name=username)
            if user_list:
                return user_list[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get hotspot user {username}: {str(e)}")
            return None

    def close(self):
        """Close connection to RouterOS."""
        try:
            if self.connection:
                self.connection.close()
                logger.info("RouterOS connection closed")
        except Exception as e:
            logger.error(f"Error closing connection: {str(e)}")


class MikroTikManager:
    """Singleton manager for MikroTik router operations."""

    _instance = None
    _connection: Optional[RouterConnection] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._initialize_connection()

    def _initialize_connection(self):
        """Initialize router connection based on configuration."""
        mikrotik_enabled = os.getenv("MIKROTIK_ENABLED", "false").lower() == "true"

        if not mikrotik_enabled:
            logger.info("MikroTik integration disabled, using mock connection")
            self._connection = MockRouterConnection()
            return

        host = os.getenv("MIKROTIK_HOST", "192.168.88.1")
        username = os.getenv("MIKROTIK_USERNAME", "admin")
        password = os.getenv("MIKROTIK_PASSWORD", "")
        use_ssl = os.getenv("MIKROTIK_USE_SSL", "false").lower() == "true"

        try:
            self._connection = RealRouterConnection(host, username, password, use_ssl)
            logger.info("Real RouterOS connection established")
        except RouterConnectionError as e:
            logger.warning(f"Failed to connect to real RouterOS: {e}. Falling back to mock.")
            self._connection = MockRouterConnection(host, username, password)

    def get_connection(self) -> RouterConnection:
        """Get the current router connection."""
        if self._connection is None:
            self._initialize_connection()
        return self._connection

    def create_hotspot_user(
        self,
        username: str,
        password: str,
        profile: str = "default"
    ) -> Dict[str, Any]:
        """Create a hotspot user."""
        try:
            connection = self.get_connection()
            return connection.create_hotspot_user(username, password, profile)
        except Exception as e:
            logger.error(f"Hotspot user creation error: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "username": username,
            }

    def remove_hotspot_user(self, username: str) -> bool:
        """Remove a hotspot user."""
        try:
            connection = self.get_connection()
            return connection.remove_hotspot_user(username)
        except Exception as e:
            logger.error(f"Hotspot user removal error: {str(e)}")
            return False

    def get_hotspot_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get hotspot user details."""
        try:
            connection = self.get_connection()
            return connection.get_hotspot_user(username)
        except Exception as e:
            logger.error(f"Get hotspot user error: {str(e)}")
            return None

    def test_connection(self) -> bool:
        """Test router connection."""
        try:
            connection = self.get_connection()
            return connection.test_connection()
        except Exception as e:
            logger.error(f"Connection test error: {str(e)}")
            return False


# Global instance
_manager = None


def get_mikrotik_manager() -> MikroTikManager:
    """Get global MikroTik manager instance."""
    global _manager
    if _manager is None:
        _manager = MikroTikManager()
    return _manager


def create_hotspot_user(username: str, password: str, profile: str = "default") -> Dict[str, Any]:
    """Convenience function to create hotspot user."""
    return get_mikrotik_manager().create_hotspot_user(username, password, profile)


def remove_hotspot_user(username: str) -> bool:
    """Convenience function to remove hotspot user."""
    return get_mikrotik_manager().remove_hotspot_user(username)


def get_hotspot_user(username: str) -> Optional[Dict[str, Any]]:
    """Convenience function to get hotspot user."""
    return get_mikrotik_manager().get_hotspot_user(username)


def test_mikrotik_connection() -> bool:
    """Convenience function to test router connection."""
    return get_mikrotik_manager().test_connection()
