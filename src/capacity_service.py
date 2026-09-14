"""
Capacity and scheduling service.
Tracks cleaning bay and biomedical technician capacity per shift,
proposes realistic turnaround slots, and safely reports when capacity is exhausted.
"""

from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
import sqlite3

class CapacityService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_available_slot(self, role: str) -> Dict[str, Any]:
        """
        Find the earliest slot where booked < capacity for the given role ('cleaning_bay' or 'technician').
        Returns slot details or indicates exhaustion.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT slot_id, shift_date, shift_name, role, capacity, booked
            FROM capacity_slots
            WHERE role = ? AND booked < capacity
            ORDER BY shift_date ASC, 
                CASE shift_name 
                    WHEN 'Morning' THEN 1 
                    WHEN 'Afternoon' THEN 2 
                    WHEN 'Night' THEN 3 
                    ELSE 4 
                END ASC
            LIMIT 1;
        """, (role,))
        row = cursor.fetchone()
        if row:
            remaining = row["capacity"] - row["booked"]
            return {
                "available": True,
                "slot_id": row["slot_id"],
                "shift_date": row["shift_date"],
                "shift_name": row["shift_name"],
                "role": row["role"],
                "remaining_capacity": remaining,
                "label": f"{row['shift_date']} ({row['shift_name']} shift) - {remaining} slots remaining"
            }
        
        # If no slot is available in current table
        cursor.execute("""
            SELECT MAX(shift_date) as max_date FROM capacity_slots WHERE role = ?;
        """, (role,))
        max_row = cursor.fetchone()
        earliest_recheck = max_row["max_date"] if max_row and max_row["max_date"] else date.today().isoformat()

        return {
            "available": False,
            "slot_id": None,
            "earliest_recheck": f"{earliest_recheck} (Shift Queue Overloaded)",
            "label": "No capacity available in visible scheduling window. Earliest queue re-check tomorrow at 08:00 AM."
        }

    def book_slot(self, slot_id: str) -> bool:
        """Atomically increments booked count if capacity remains."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE capacity_slots
            SET booked = booked + 1
            WHERE slot_id = ? AND booked < capacity;
        """, (slot_id,))
        return cursor.rowcount > 0

    def get_capacity_summary(self) -> List[Dict[str, Any]]:
        """Returns capacity utilization per shift for reporting dashboard."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT slot_id, shift_date, shift_name, role, capacity, booked,
                   ROUND((CAST(booked AS REAL) / CAST(capacity AS REAL)) * 100, 1) as utilization_pct
            FROM capacity_slots
            ORDER BY shift_date ASC, 
                CASE shift_name 
                    WHEN 'Morning' THEN 1 
                    WHEN 'Afternoon' THEN 2 
                    WHEN 'Night' THEN 3 
                    ELSE 4 
                END ASC;
        """)
        return [dict(row) for row in cursor.fetchall()]
