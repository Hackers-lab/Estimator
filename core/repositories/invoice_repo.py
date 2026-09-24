"""
core/repositories/invoice_repo.py
================================
Repository for invoices, measurement book records, and project billing metadata.
"""
from __future__ import annotations
import json
import sqlite3
from core.repositories.base import get_connection

def save_project_metadata(name: str, path: str, type: str, lat: str, lon: str, cost: float,
                          project_id: str = "", po_no: str = "", po_date: str = "",
                          vendor_id: str = "", comm_date: str = "", comp_date: str = "",
                          meas_date: str = "", meas_taken_by: str = "", certified_by: str = "") -> None:
    con = get_connection()
    try:
        con.execute(
            "INSERT INTO projects (project_name, file_path, project_type, latitude, longitude, estimated_cost, "
            "project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "project_name=excluded.project_name, "
            "project_type=excluded.project_type, "
            "latitude=excluded.latitude, "
            "longitude=excluded.longitude, "
            "estimated_cost=excluded.estimated_cost, "
            "project_id=excluded.project_id, "
            "po_no=excluded.po_no, "
            "po_date=excluded.po_date, "
            "vendor_id=excluded.vendor_id, "
            "comm_date=excluded.comm_date, "
            "comp_date=excluded.comp_date, "
            "meas_date=excluded.meas_date, "
            "meas_taken_by=excluded.meas_taken_by, "
            "certified_by=excluded.certified_by, "
            "updated_at=CURRENT_TIMESTAMP",
            (name, path, type, lat, lon, cost, project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by)
        )
        con.commit()
    finally:
        con.close()

def update_project_billing_metadata(path: str, project_id: str, po_no: str, po_date: str,
                                   vendor_id: str, comm_date: str, comp_date: str,
                                   meas_date: str, meas_taken_by: str, certified_by: str) -> None:
    con = get_connection()
    try:
        con.execute(
            "UPDATE projects SET "
            "project_id=?, po_no=?, po_date=?, vendor_id=?, comm_date=?, comp_date=?, meas_date=?, "
            "meas_taken_by=?, certified_by=?, updated_at=CURRENT_TIMESTAMP WHERE file_path=?",
            (project_id, po_no, po_date, vendor_id, comm_date, comp_date, meas_date, meas_taken_by, certified_by, path)
        )
        con.commit()
    finally:
        con.close()

def delete_project_metadata(path: str) -> None:
    con = get_connection()
    try:
        con.execute("DELETE FROM projects WHERE file_path=?", (path,))
        con.commit()
    finally:
        con.close()

def rename_project_metadata(old_path: str, new_path: str, new_name: str) -> None:
    con = get_connection()
    try:
        con.execute(
            "UPDATE projects SET file_path=?, project_name=?, updated_at=CURRENT_TIMESTAMP WHERE file_path=?",
            (new_path, new_name, old_path)
        )
        con.commit()
    finally:
        con.close()

def save_bill(bill_data: dict) -> bool:
    con = get_connection()
    try:
        con.execute(
            "INSERT INTO bills (invoice_no, invoice_date, project_id, po_no, po_date, copy_type, "
            "client_name, client_address, client_gstin, description, labor_total, supervision, "
            "gst, cess, grand_total, project_paths, items_json, meas_taken_by, certified_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(invoice_no) DO UPDATE SET "
            "invoice_date=excluded.invoice_date, "
            "project_id=excluded.project_id, "
            "po_no=excluded.po_no, "
            "po_date=excluded.po_date, "
            "copy_type=excluded.copy_type, "
            "client_name=excluded.client_name, "
            "client_address=excluded.client_address, "
            "client_gstin=excluded.client_gstin, "
            "description=excluded.description, "
            "labor_total=excluded.labor_total, "
            "supervision=excluded.supervision, "
            "gst=excluded.gst, "
            "cess=excluded.cess, "
            "grand_total=excluded.grand_total, "
            "project_paths=excluded.project_paths, "
            "items_json=excluded.items_json, "
            "meas_taken_by=excluded.meas_taken_by, "
            "certified_by=excluded.certified_by",
            (
                bill_data["invoice_no"],
                bill_data["invoice_date"],
                bill_data["project_id"],
                bill_data["po_no"],
                bill_data["po_date"],
                bill_data["copy_type"],
                bill_data["client_name"],
                bill_data["client_address"],
                bill_data.get("client_gstin", ""),
                bill_data.get("description", ""),
                bill_data["labor_total"],
                bill_data.get("supervision", 0.0),
                bill_data["gst"],
                bill_data.get("cess", 0.0),
                bill_data["grand_total"],
                json.dumps(bill_data["project_paths"]),
                json.dumps(bill_data["items"]),
                bill_data.get("meas_taken_by", ""),
                bill_data.get("certified_by", "")
            )
        )
        con.commit()
        return True
    except sqlite3.Error as e:
        print(f"[DB] Error saving bill: {e}")
        return False
    finally:
        con.close()

def get_bills() -> list[dict]:
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT id, invoice_no, invoice_date, project_id, po_no, po_date, copy_type, "
            "client_name, client_address, client_gstin, description, labor_total, supervision, "
            "gst, cess, grand_total, project_paths, items_json, datetime(created_at, 'localtime'), "
            "meas_taken_by, certified_by "
            "FROM bills ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                "id": r[0],
                "invoice_no": r[1],
                "invoice_date": r[2],
                "project_id": r[3],
                "po_no": r[4],
                "po_date": r[5],
                "copy_type": r[6],
                "client_name": r[7],
                "client_address": r[8],
                "client_gstin": r[9],
                "description": r[10],
                "labor_total": r[11],
                "supervision": r[12],
                "gst": r[13],
                "cess": r[14],
                "grand_total": r[15],
                "project_paths": json.loads(r[16]),
                "items": json.loads(r[17]),
                "created_at": r[18],
                "meas_taken_by": r[19] if len(r) > 19 else "",
                "certified_by": r[20] if len(r) > 20 else ""
            }
            for r in rows
        ]
    finally:
        con.close()

def delete_bill(bill_id: int) -> None:
    con = get_connection()
    try:
        con.execute("DELETE FROM bills WHERE id=?", (bill_id,))
        con.commit()
    finally:
        con.close()
