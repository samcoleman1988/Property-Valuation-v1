"""SQLite property database for saving every analysed property.

Stores listing details, valuation outputs, scores, and user notes.
Designed for reviewing past analyses and tracking portfolio.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any


DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "properties.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    address TEXT,
    postcode TEXT,
    property_type TEXT,
    bedrooms INTEGER,
    bathrooms INTEGER,
    floor_area_sqm REAL,
    tenure TEXT,
    asking_price REAL,

    -- Valuation outputs
    fair_value_conservative REAL,
    fair_value_balanced REAL,
    fair_value_aggressive REAL,
    confidence_score INTEGER,
    confidence_label TEXT,
    asking_vs_fair_gap_pct REAL,
    investment_tagline TEXT,

    -- Offer strategy
    suggested_initial_offer REAL,
    max_sensible_offer REAL,
    walk_away_price REAL,

    -- Scorecard
    overall_score REAL,
    overall_label TEXT,
    verdict TEXT,
    recommendation TEXT,

    -- Risk
    risk_level TEXT,
    risk_count INTEGER,

    -- Full JSON blobs for detailed review
    valuation_json TEXT,
    scorecard_json TEXT,
    risk_json TEXT,
    listing_json TEXT,
    comparable_json TEXT,

    -- User fields
    notes TEXT DEFAULT '',
    eventual_sale_price REAL,
    offer_made REAL,
    offer_accepted INTEGER DEFAULT 0,
    status TEXT DEFAULT 'analysed',

    -- Metadata
    analysis_date TEXT,
    analysis_mode TEXT DEFAULT 'personal',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_postcode ON properties(postcode);
CREATE INDEX IF NOT EXISTS idx_analysis_date ON properties(analysis_date);
CREATE INDEX IF NOT EXISTS idx_status ON properties(status);

CREATE TABLE IF NOT EXISTS calibration_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id),

    -- Human judgement on valuation accuracy
    valuation_judgement TEXT DEFAULT '',
    -- one of: credible, too_optimistic, too_conservative,
    --         wrong_comparables, missing_dev_upside,
    --         missing_risk, insufficient_data

    -- Comparable quality
    comparable_quality TEXT DEFAULT '',
    -- one of: good, acceptable, poor, wrong_type, too_broad

    -- Investment verdict assessment
    verdict_judgement TEXT DEFAULT '',
    -- one of: right, partially_right, wrong

    -- Free text
    what_tool_missed TEXT DEFAULT '',
    manual_adjustment_notes TEXT DEFAULT '',
    general_notes TEXT DEFAULT '',

    -- Model error categories (comma-separated tags)
    error_tags TEXT DEFAULT '',
    -- e.g. postcode_too_broad, wrong_property_type, no_floor_area,
    --      rural_comps_diverse, flats_misweighted,
    --      extension_underestimated, btl_assumptions_weak

    -- Outcome tracking
    viewed INTEGER DEFAULT 0,
    offered INTEGER DEFAULT 0,
    offer_amount REAL,
    outcome TEXT DEFAULT '',
    -- one of: '', not_pursued, offered_rejected, offered_accepted,
    --         purchased, sold_to_other
    eventual_sold_price REAL,

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cal_property ON calibration_log(property_id);
"""


def _get_connection() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def save_property(
    url: str,
    address: str,
    postcode: str,
    property_type: str,
    bedrooms: int,
    bathrooms: int,
    floor_area_sqm: float,
    tenure: str,
    asking_price: float,
    valuation_result: dict,
    scorecard_result: dict,
    risk_result: dict,
    listing_data: dict,
    comparable_data: dict,
    mode: str = "personal",
    notes: str = "",
) -> int:
    """Save a property analysis to the database. Returns the row ID."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO properties (
                url, address, postcode, property_type, bedrooms, bathrooms,
                floor_area_sqm, tenure, asking_price,
                fair_value_conservative, fair_value_balanced, fair_value_aggressive,
                confidence_score, confidence_label, asking_vs_fair_gap_pct,
                investment_tagline,
                suggested_initial_offer, max_sensible_offer, walk_away_price,
                overall_score, overall_label, verdict, recommendation,
                risk_level, risk_count,
                valuation_json, scorecard_json, risk_json, listing_json, comparable_json,
                notes, analysis_date, analysis_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                url, address, postcode, property_type, bedrooms, bathrooms,
                floor_area_sqm, tenure, asking_price,
                valuation_result.get("fair_value_conservative", 0),
                valuation_result.get("fair_value_balanced", 0),
                valuation_result.get("fair_value_aggressive", 0),
                valuation_result.get("confidence_score", 0),
                valuation_result.get("confidence_label", ""),
                valuation_result.get("asking_vs_fair_gap_pct", 0),
                valuation_result.get("investment_tagline", ""),
                valuation_result.get("suggested_initial_offer", 0),
                valuation_result.get("max_sensible_offer", 0),
                valuation_result.get("walk_away_price", 0),
                scorecard_result.get("overall_score", 0),
                scorecard_result.get("overall_label", ""),
                scorecard_result.get("verdict", ""),
                scorecard_result.get("recommendation", ""),
                risk_result.get("overall_risk_level", ""),
                len(risk_result.get("flags", [])),
                json.dumps(valuation_result),
                json.dumps(scorecard_result),
                json.dumps(risk_result),
                json.dumps(listing_data),
                json.dumps(comparable_data),
                notes,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                mode,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_properties() -> List[Dict[str, Any]]:
    """Get all saved properties, most recent first."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM properties ORDER BY created_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_property(property_id: int) -> Optional[Dict[str, Any]]:
    """Get a single property by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM properties WHERE id = ?", (property_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_notes(property_id: int, notes: str):
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE properties SET notes = ?, updated_at = datetime('now') WHERE id = ?",
            (notes, property_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_offer(property_id: int, offer_made: float, accepted: bool = False):
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE properties SET offer_made = ?, offer_accepted = ?, "
            "status = ?, updated_at = datetime('now') WHERE id = ?",
            (offer_made, 1 if accepted else 0, "offered", property_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_sale_price(property_id: int, sale_price: float):
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE properties SET eventual_sale_price = ?, "
            "status = 'sold', updated_at = datetime('now') WHERE id = ?",
            (sale_price, property_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_property(property_id: int):
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM properties WHERE id = ?", (property_id,))
        conn.commit()
    finally:
        conn.close()


# --- Calibration log ---

def get_calibration(property_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM calibration_log WHERE property_id = ?",
            (property_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_calibration(property_id: int, data: Dict[str, Any]) -> int:
    """Upsert calibration feedback for a property."""
    conn = _get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM calibration_log WHERE property_id = ?",
            (property_id,),
        ).fetchone()

        cols = [
            "valuation_judgement", "comparable_quality", "verdict_judgement",
            "what_tool_missed", "manual_adjustment_notes", "general_notes",
            "error_tags", "viewed", "offered", "offer_amount", "outcome",
            "eventual_sold_price",
        ]

        if existing:
            sets = ", ".join(f"{c} = ?" for c in cols)
            sets += ", updated_at = datetime('now')"
            vals = [data.get(c, "") for c in cols]
            vals.append(existing["id"])
            conn.execute(f"UPDATE calibration_log SET {sets} WHERE id = ?", vals)
            conn.commit()
            return existing["id"]
        else:
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            vals = [data.get(c, "") for c in cols]
            vals.insert(0, property_id)
            cursor = conn.execute(
                f"INSERT INTO calibration_log (property_id, {col_names}) "
                f"VALUES (?, {placeholders})",
                vals,
            )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def get_all_calibrations() -> List[Dict[str, Any]]:
    conn = _get_connection()
    try:
        rows = conn.execute(
            """SELECT p.id, p.address, p.postcode, p.property_type, p.bedrooms,
                      p.asking_price, p.fair_value_balanced,
                      p.asking_vs_fair_gap_pct, p.overall_score, p.verdict,
                      p.risk_count, p.confidence_label, p.investment_tagline,
                      p.analysis_date, p.url,
                      p.valuation_json,
                      c.valuation_judgement, c.comparable_quality,
                      c.verdict_judgement, c.viewed, c.offered,
                      c.offer_amount, c.outcome, c.eventual_sold_price,
                      c.error_tags, c.what_tool_missed
               FROM properties p
               LEFT JOIN calibration_log c ON c.property_id = p.id
               ORDER BY p.created_at DESC""",
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_error_tag_summary() -> List[Dict[str, Any]]:
    """Count how often each error tag appears across calibration entries."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT error_tags FROM calibration_log WHERE error_tags != ''"
        ).fetchall()
        counts: Dict[str, int] = {}
        for row in rows:
            for tag in row["error_tags"].split(","):
                tag = tag.strip()
                if tag:
                    counts[tag] = counts.get(tag, 0) + 1
        result = [{"tag": k, "count": v} for k, v in
                  sorted(counts.items(), key=lambda x: -x[1])]
        return result
    finally:
        conn.close()
