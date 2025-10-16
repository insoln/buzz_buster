"""Test suspicious user status persistence across service restarts."""
import pytest
import sys
import os
from unittest.mock import Mock, patch

# Add the bot directory to the path so we can import the app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bot'))

from app.database import (
    check_and_create_tables,
    load_user_caches, 
    suspicious_users_cache,
    spammers_cache
)
from app.config import DB_CONFIG
import mysql.connector


@pytest.fixture
def test_db_config():
    """Use a test database configuration."""
    return {
        "host": DB_CONFIG.get("host", "localhost"),
        "port": DB_CONFIG.get("port", 3306),
        "user": DB_CONFIG.get("user", "root"),
        "password": DB_CONFIG.get("password", ""),
        "database": "buzz_buster_test"
    }


def setup_test_database(test_db_config):
    """Set up test database and tables."""
    # Create test database if it doesn't exist
    config_without_db = test_db_config.copy()
    del config_without_db["database"]
    
    try:
        conn = mysql.connector.connect(**config_without_db)
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {test_db_config['database']}")
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error:
        # Database might not be available in test environment
        pytest.skip("MySQL database not available for testing")

    # Now connect to the test database and create tables
    try:
        with patch('app.database.DB_CONFIG', test_db_config):
            check_and_create_tables()
    except mysql.connector.Error:
        pytest.skip("Cannot connect to test database")


def cleanup_test_data(test_db_config, user_id):
    """Clean up test data after test."""
    try:
        conn = mysql.connector.connect(**test_db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_entries WHERE user_id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
    except mysql.connector.Error:
        pass  # Ignore cleanup errors


def test_suspicious_user_persistence_across_restarts(test_db_config):
    """Test that suspicious user status is preserved across service restarts."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12345
    test_group_id = 67890
    
    try:
        # Simulate adding a suspicious user to database (like when user joins group)
        with patch('app.database.DB_CONFIG', test_db_config):
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Insert user as suspicious (simulating user joining group)
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, suspicious, seen_message, spammer)
                VALUES (%s, %s, NOW(), TRUE, FALSE, FALSE)
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Simulate service restart - reload caches from database
            load_user_caches()
            
            # Verify that the user is loaded as suspicious
            assert test_user_id in suspicious_users_cache, f"User {test_user_id} should be in suspicious cache after restart"
            assert test_user_id not in spammers_cache, f"User {test_user_id} should not be in spammers cache"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)


def test_suspicious_user_cleared_after_good_message(test_db_config):
    """Test that suspicious status is cleared when user sends a good message."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12346
    test_group_id = 67891
    
    try:
        with patch('app.database.DB_CONFIG', test_db_config):
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Insert user as suspicious
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, suspicious, seen_message, spammer)
                VALUES (%s, %s, NOW(), TRUE, FALSE, FALSE)
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            
            # Simulate user sending a good message (not spam)
            cursor.execute(
                """
                UPDATE user_entries SET seen_message = TRUE, spammer = FALSE, suspicious = FALSE WHERE user_id = %s
                """,
                (test_user_id,)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Simulate service restart - reload caches from database
            load_user_caches()
            
            # Verify that the user is no longer suspicious
            assert test_user_id not in suspicious_users_cache, f"User {test_user_id} should not be in suspicious cache after good message"
            assert test_user_id not in spammers_cache, f"User {test_user_id} should not be in spammers cache"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)


def test_spammer_marked_correctly(test_db_config):
    """Test that users marked as spammers are handled correctly."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12347
    test_group_id = 67892
    
    try:
        with patch('app.database.DB_CONFIG', test_db_config):
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Insert user as suspicious initially
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, suspicious, seen_message, spammer)
                VALUES (%s, %s, NOW(), TRUE, FALSE, FALSE)
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            
            # Simulate user being marked as spammer
            cursor.execute(
                """
                UPDATE user_entries SET spammer = TRUE, suspicious = FALSE where user_id=%s and group_id = %s
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Simulate service restart - reload caches from database
            load_user_caches()
            
            # Verify that the user is now in spammers cache and not suspicious
            assert test_user_id in spammers_cache, f"User {test_user_id} should be in spammers cache"
            assert test_user_id not in suspicious_users_cache, f"User {test_user_id} should not be in suspicious cache after being marked as spammer"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)