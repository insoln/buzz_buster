"""Test trust-based system and per-group spammer persistence across service restarts."""
import pytest
import sys
import os
from unittest.mock import Mock, patch

# Add the bot directory to the path so we can import the app modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bot'))

from app.database import (
    check_and_create_tables,
    load_user_caches, 
    spammers_cache,
    is_user_trusted,
    is_user_spammer_anywhere,
    is_user_spammer_in_group
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
        
        # Also clear from cache if present
        global spammers_cache
        if user_id in spammers_cache:
            del spammers_cache[user_id]
            
    except mysql.connector.Error:
        pass  # Ignore cleanup errors


def test_trusted_user_status_across_restarts(test_db_config):
    """Test that trusted user status works correctly across service restarts."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12345
    test_group_id = 67890
    
    try:
        # Simulate adding a trusted user to database (user who sent a message)
        with patch('app.database.DB_CONFIG', test_db_config):
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Insert user as trusted (simulating user who sent a good message)
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, seen_message, spammer)
                VALUES (%s, %s, NOW(), TRUE, FALSE)
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Verify that the user is trusted
            assert is_user_trusted(test_user_id), f"User {test_user_id} should be trusted"
            assert not is_user_spammer_anywhere(test_user_id), f"User {test_user_id} should not be a spammer"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)


def test_unknown_user_becomes_trusted_after_good_message(test_db_config):
    """Test that unknown users become trusted when they send good messages."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12346
    test_group_id = 67891
    
    try:
        with patch('app.database.DB_CONFIG', test_db_config):
            # Initially, user is not in database (unknown user)
            assert not is_user_trusted(test_user_id), f"User {test_user_id} should not be trusted initially"
            assert not is_user_spammer_anywhere(test_user_id), f"User {test_user_id} should not be a spammer initially"
            
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Simulate user sending a good message (becomes trusted)
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, seen_message, spammer)
                VALUES (%s, %s, NOW(), TRUE, FALSE)
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Verify that the user is now trusted
            assert is_user_trusted(test_user_id), f"User {test_user_id} should be trusted after good message"
            assert not is_user_spammer_anywhere(test_user_id), f"User {test_user_id} should not be a spammer"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)


def test_per_group_spammer_tracking(test_db_config):
    """Test that per-group spammer tracking works correctly across restarts."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12347
    test_group_id_1 = 67892
    test_group_id_2 = 67893
    
    try:
        with patch('app.database.DB_CONFIG', test_db_config):
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Insert user as spammer in group 1
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, seen_message, spammer)
                VALUES (%s, %s, NOW(), FALSE, TRUE)
                """,
                (test_user_id, test_group_id_1)
            )
            
            # Insert user as non-spammer in group 2  
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, seen_message, spammer)
                VALUES (%s, %s, NOW(), TRUE, FALSE)
                """,
                (test_user_id, test_group_id_2)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Simulate service restart - reload caches from database
            load_user_caches()
            
            # Verify per-group spammer status
            assert is_user_spammer_anywhere(test_user_id), f"User {test_user_id} should be a spammer anywhere"
            assert is_user_spammer_in_group(test_user_id, test_group_id_1), f"User {test_user_id} should be spammer in group {test_group_id_1}"
            assert not is_user_spammer_in_group(test_user_id, test_group_id_2), f"User {test_user_id} should not be spammer in group {test_group_id_2}"
            
            # Verify cache structure
            assert test_user_id in spammers_cache, f"User {test_user_id} should be in spammers cache"
            assert test_group_id_1 in spammers_cache[test_user_id], f"Group {test_group_id_1} should be in user's spammer groups"
            assert test_group_id_2 not in spammers_cache[test_user_id], f"Group {test_group_id_2} should not be in user's spammer groups"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)


def test_cross_group_spammer_detection(test_db_config):
    """Test that cross-group spammer detection works correctly."""
    
    setup_test_database(test_db_config)
    
    test_user_id = 12348
    test_group_id = 67894
    
    try:
        with patch('app.database.DB_CONFIG', test_db_config):
            conn = mysql.connector.connect(**test_db_config)
            cursor = conn.cursor()
            
            # Insert user as spammer in one group
            cursor.execute(
                """
                INSERT INTO user_entries (user_id, group_id, join_date, seen_message, spammer)
                VALUES (%s, %s, NOW(), FALSE, TRUE)
                """,
                (test_user_id, test_group_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            # Simulate service restart - reload caches from database
            load_user_caches()
            
            # Verify that user is detected as spammer anywhere
            assert is_user_spammer_anywhere(test_user_id), f"User {test_user_id} should be detected as spammer anywhere"
            
    finally:
        cleanup_test_data(test_db_config, test_user_id)