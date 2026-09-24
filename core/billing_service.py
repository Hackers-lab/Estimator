"""
core/billing_service.py
=======================
Headless financial, tax, and measurement book calculation service for billing.
"""
from __future__ import annotations
import math

def calculate_taxes(labor_base: float, cgst_rate: float = 0.09, sgst_rate: float = 0.09) -> dict[str, float]:
    """Calculate CGST, SGST, Total GST, and Grand Total on labor base amount."""
    cgst_amt = round(labor_base * cgst_rate, 2)
    sgst_amt = round(labor_base * sgst_rate, 2)
    gst_amt = round(cgst_amt + sgst_amt, 2)
    grand_total = round(labor_base + gst_amt, 2)
    return {
        "labor_base": labor_base,
        "cgst_rate": cgst_rate,
        "cgst_amount": cgst_amt,
        "sgst_rate": sgst_rate,
        "sgst_amount": sgst_amt,
        "gst_total": gst_amt,
        "grand_total": grand_total,
    }

def amount_to_indian_rupees_words(num: float | None) -> str:
    """Convert a numeric amount into Indian Rupees in words (Lakhs/Crores convention)."""
    if num is None:
        return ""
    num = round(num, 2)
    int_part = int(math.floor(num))
    frac_part = int(round((num - int_part) * 100))

    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
             "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def num_to_words_int(n: int) -> str:
        if n == 0:
            return "Zero"

        def convert_chunk(val: int) -> str:
            res = []
            if val >= 100:
                res.append(units[val // 100] + " Hundred")
                val %= 100
            if val >= 20:
                res.append(tens[val // 10])
                val %= 10
            if val > 0:
                res.append(units[val])
            return " ".join(res)

        words = []
        if n >= 10000000:
            words.append(num_to_words_int(n // 10000000) + " Crore")
            n %= 10000000
        if n >= 100000:
            words.append(convert_chunk(n // 100000) + " Lakh")
            n %= 100000
        if n >= 1000:
            words.append(convert_chunk(n // 1000) + " Thousand")
            n %= 1000
        if n > 0:
            words.append(convert_chunk(n))
        return " ".join(words)

    int_words = num_to_words_int(int_part)
    words_str = f"Rupees {int_words}" if int_part > 0 else "Rupees Zero"
    if frac_part > 0:
        frac_words = num_to_words_int(frac_part)
        words_str += f" and {frac_words} Paise"
    words_str += " Only"
    return words_str
