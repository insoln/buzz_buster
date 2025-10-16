#!/usr/bin/env python3
"""
Utility script to update spam detection instructions for all configured groups.
This script reads instructions from the INSTRUCTIONS_DEFAULT_TEXT environment variable
and updates all groups in the database to use these instructions.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'bot'))

import mysql.connector
from app.config import DB_CONFIG, INSTRUCTIONS_DEFAULT_TEXT
from app.logging_setup import logger


def update_all_group_instructions():
    """Update instructions for all configured groups in the database."""
    
    print("=" * 80)
    print("UPDATING SPAM DETECTION INSTRUCTIONS FOR ALL GROUPS")
    print("=" * 80)
    
    print(f"Instructions source: {'Environment variable INSTRUCTIONS_DEFAULT_TEXT' if os.getenv('INSTRUCTIONS_DEFAULT_TEXT') else 'Default fallback in config.py'}")
    print(f"Instructions length: {len(INSTRUCTIONS_DEFAULT_TEXT)} characters")
    print(f"First 200 characters: {INSTRUCTIONS_DEFAULT_TEXT[:200]}...")
    
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Get all configured groups
        cursor.execute("SELECT group_id FROM `groups`")
        groups = cursor.fetchall()
        
        if not groups:
            print("No configured groups found in database.")
            return
        
        print(f"\nFound {len(groups)} configured groups. Updating instructions...")
        
        updated_count = 0
        for (group_id,) in groups:
            try:
                # Update or insert instructions for this group
                cursor.execute(
                    """
                    INSERT INTO group_settings (group_id, parameter, value) 
                    VALUES (%s, %s, %s) 
                    ON DUPLICATE KEY UPDATE value = %s
                    """,
                    (group_id, "instructions", INSTRUCTIONS_DEFAULT_TEXT, INSTRUCTIONS_DEFAULT_TEXT)
                )
                updated_count += 1
                print(f"✓ Updated group {group_id}")
                
            except mysql.connector.Error as err:
                print(f"✗ Failed to update group {group_id}: {err}")
        
        conn.commit()
        
        print(f"\n✅ Successfully updated instructions for {updated_count} out of {len(groups)} groups.")
        
        # Verify the updates
        print("\nVerifying updates...")
        cursor.execute(
            """
            SELECT g.group_id, s.value 
            FROM `groups` g 
            LEFT JOIN group_settings s ON g.group_id = s.group_id AND s.parameter = 'instructions'
            """
        )
        verification_results = cursor.fetchall()
        
        for group_id, instructions in verification_results:
            if instructions:
                status = "✓ Has instructions" if len(instructions) > 100 else "⚠ Short instructions"
                print(f"  Group {group_id}: {status} ({len(instructions) if instructions else 0} chars)")
            else:
                print(f"  Group {group_id}: ✗ No instructions found")
        
    except mysql.connector.Error as err:
        print(f"❌ Database error: {err}")
        return False
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()
    
    return True


def show_current_instructions():
    """Display current instructions from environment/config."""
    
    print("\n" + "=" * 80)
    print("CURRENT INSTRUCTIONS CONFIGURATION")
    print("=" * 80)
    
    env_instructions = os.getenv("INSTRUCTIONS_DEFAULT_TEXT")
    if env_instructions:
        print("✓ Instructions loaded from INSTRUCTIONS_DEFAULT_TEXT environment variable")
        print(f"  Length: {len(env_instructions)} characters")
    else:
        print("⚠ No INSTRUCTIONS_DEFAULT_TEXT in environment, using config.py default")
        print(f"  Default: '{INSTRUCTIONS_DEFAULT_TEXT}'")
        print(f"  Length: {len(INSTRUCTIONS_DEFAULT_TEXT)} characters")
    
    print(f"\nFull instructions text:")
    print("-" * 40)
    print(INSTRUCTIONS_DEFAULT_TEXT)
    print("-" * 40)


def main():
    """Main function."""
    
    if len(sys.argv) > 1 and sys.argv[1] == "--show":
        show_current_instructions()
        return 0
    
    print("This script will update spam detection instructions for all configured groups.")
    print("The instructions will be taken from the INSTRUCTIONS_DEFAULT_TEXT environment variable.")
    print("\nCurrent configuration:")
    
    show_current_instructions()
    
    print("\n" + "=" * 80)
    response = input("Do you want to proceed with updating all groups? (y/N): ")
    
    if response.lower() not in ['y', 'yes']:
        print("Operation cancelled.")
        return 0
    
    success = update_all_group_instructions()
    
    if success:
        print("\n🎉 All groups have been updated with the new instructions!")
        print("The improved prompt engineering will now be used for spam detection.")
        return 0
    else:
        print("\n❌ Update failed. Please check the database configuration and try again.")
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)