"""Fetch comparables for all 20 properties and cache to disk (JSON).

Run this ONCE — it hits the API. Then test_es_cached.py re-runs
the V2 engine instantly from the cached evidence.
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from src.rightmove_parser import PropertyListing
from src.comparable_engine import fetch_and_score_comparables
from src.epc import lookup_subject_floor_area
from pathlib import Path

PROPERTIES = [
    {"label": "1. Ruttle Close, Cholsey (semi, 3bed, OX10)",
     "listing": PropertyListing(
         address="Ruttle Close, Cholsey", postcode="OX10 9QT",
         asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Ruttle Close", overrides_applied=["Street: Ruttle Close"])},
    {"label": "2. Chestnut Close, Witney (semi, 3bed, OX28)",
     "listing": PropertyListing(
         address="Chestnut Close, Witney", postcode="OX28 1GH",
         asking_price=425000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Chestnut Close", overrides_applied=["Street: Chestnut Close"])},
    {"label": "3. Thorney Leys, Witney (terr, 3bed, OX28)",
     "listing": PropertyListing(
         address="Thorney Leys, Witney", postcode="OX28 5NR",
         asking_price=275000, property_type="Terraced", bedrooms=3, tenure="Freehold",
         override_street_name="Thorney Leys", overrides_applied=["Street: Thorney Leys"])},
    {"label": "4. Ingestre Road, Prenton (flat, 2bed, CH43)",
     "listing": PropertyListing(
         address="Ingestre Road, Prenton", postcode="CH43 5UX",
         asking_price=160000, property_type="Flat", bedrooms=2, tenure="Leasehold",
         override_street_name="Ingestre Road", overrides_applied=["Street: Ingestre Road"])},
    {"label": "5. Vyner Rd South, Prenton (semi, 3bed, CH43)",
     "listing": PropertyListing(
         address="Vyner Road South, Prenton", postcode="CH43 7PN",
         asking_price=230000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Vyner Road South", overrides_applied=["Street: Vyner Road South"])},
    {"label": "6. Willowbank Rd, Birkenhead (terr, 2bed, CH42)",
     "listing": PropertyListing(
         address="Willowbank Road, Birkenhead", postcode="CH42 7JZ",
         asking_price=120000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Willowbank Road", overrides_applied=["Street: Willowbank Road"])},
    {"label": "7. Magazine Lane, Wallasey (semi, 3bed, CH45)",
     "listing": PropertyListing(
         address="Magazine Lane, New Brighton", postcode="CH45 1HW",
         asking_price=185000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Magazine Lane", overrides_applied=["Street: Magazine Lane"])},
    {"label": "8. Dee Park Road, Heswall (det, 4bed, CH60)",
     "listing": PropertyListing(
         address="Dee Park Road, Heswall", postcode="CH60 0BL",
         asking_price=550000, property_type="Detached House", bedrooms=4, tenure="Freehold",
         override_street_name="Dee Park Road", overrides_applied=["Street: Dee Park Road"])},
    {"label": "9. Acacia Grove, Wirral (bungalow, 2bed, CH63)",
     "listing": PropertyListing(
         address="Acacia Grove, Bebington", postcode="CH63 2HR",
         asking_price=295000, property_type="Bungalow", bedrooms=2, tenure="Freehold",
         override_street_name="Acacia Grove", overrides_applied=["Street: Acacia Grove"])},
    {"label": "10. Headley Way, Oxford (semi, 3bed, OX3)",
     "listing": PropertyListing(
         address="Headley Way, Oxford", postcode="OX3 7SU",
         asking_price=550000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Headley Way", overrides_applied=["Street: Headley Way"])},
    {"label": "11. Saxton Road, Abingdon (terr, 2bed, OX14)",
     "listing": PropertyListing(
         address="Saxton Road, Abingdon", postcode="OX14 5LN",
         asking_price=275000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Saxton Road", overrides_applied=["Street: Saxton Road"])},
    {"label": "12. Mereland Road, Didcot (semi, 3bed, OX11)",
     "listing": PropertyListing(
         address="Mereland Road, Didcot", postcode="OX11 8AZ",
         asking_price=310000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Mereland Road", overrides_applied=["Street: Mereland Road"])},
    {"label": "13. Witan Way, Witney (flat, 1bed, OX28)",
     "listing": PropertyListing(
         address="Witan Way, Witney", postcode="OX28 6FH",
         asking_price=160000, property_type="Flat", bedrooms=1, tenure="Leasehold",
         override_street_name="Witan Way", overrides_applied=["Street: Witan Way"])},
    {"label": "14. High Street, Wallingford (terr, 3bed, OX10)",
     "listing": PropertyListing(
         address="High Street, Wallingford", postcode="OX10 0BX",
         asking_price=375000, property_type="Terraced", bedrooms=3, tenure="Freehold",
         override_street_name="High Street", overrides_applied=["Street: High Street"])},
    {"label": "15. Bostock Road, Abingdon (det, 4bed, OX14)",
     "listing": PropertyListing(
         address="Bostock Road, Abingdon", postcode="OX14 1DT",
         asking_price=475000, property_type="Detached House", bedrooms=4, tenure="Freehold",
         override_street_name="Bostock Road", overrides_applied=["Street: Bostock Road"])},
    {"label": "16. Mill Street, Eynsham (terr, 2bed, OX29)",
     "listing": PropertyListing(
         address="Mill Street, Eynsham", postcode="OX29 4JX",
         asking_price=350000, property_type="Terraced", bedrooms=2, tenure="Freehold",
         override_street_name="Mill Street", overrides_applied=["Street: Mill Street"])},
    {"label": "17. Monks Close, Carterton (semi, 3bed, OX18)",
     "listing": PropertyListing(
         address="Monks Close, Carterton", postcode="OX18 3RF",
         asking_price=265000, property_type="Semi-Detached", bedrooms=3, tenure="Freehold",
         override_street_name="Monks Close", overrides_applied=["Street: Monks Close"])},
    {"label": "18. Bracken Close, Didcot (det, 3bed, OX11)",
     "listing": PropertyListing(
         address="Bracken Close, Didcot", postcode="OX11 7TG",
         asking_price=340000, property_type="Detached House", bedrooms=3, tenure="Freehold",
         override_street_name="Bracken Close", overrides_applied=["Street: Bracken Close"])},
    {"label": "19. Yewdale Park, Prenton (flat, 2bed, CH43)",
     "listing": PropertyListing(
         address="Yewdale Park, Prenton", postcode="CH43 5YQ",
         asking_price=130000, property_type="Flat", bedrooms=2, tenure="Leasehold",
         override_street_name="Yewdale Park", overrides_applied=["Street: Yewdale Park"])},
    {"label": "20. Ladygrove, Didcot (terr, 3bed, OX11)",
     "listing": PropertyListing(
         address="Ladygrove, Didcot", postcode="OX11 7UG",
         asking_price=295000, property_type="Terraced", bedrooms=3, tenure="Freehold",
         override_street_name="Ladygrove", overrides_applied=["Street: Ladygrove"])},
]

CACHE_PATH = Path(__file__).parent / "data" / "test_evidence_cache.json"

cache = {}
for i, t in enumerate(PROPERTIES):
    label = t["label"]
    listing = t["listing"]
    num = label.split(".")[0].strip()
    print(f"[{i+1}/20] Fetching {label}...", flush=True)
    start = time.time()
    try:
        addr = listing.effective_address_first_line
        pc = listing.effective_postcode
        street = listing.effective_street
        sqm, rating, detail = lookup_subject_floor_area(pc, addr, street)
        if sqm > 0 and not listing.floor_area_sqm:
            listing.floor_area_sqm = sqm
            listing.floor_area_source = "EPC"
        ev = fetch_and_score_comparables(
            postcode=pc, property_type=listing.property_type or "",
            bedrooms=listing.bedrooms or 0, floor_area_sqm=listing.floor_area_sqm or 0,
            tenure=listing.tenure or "", street=addr)
        cache[num] = {
            "label": label,
            "listing": {
                "address": listing.address,
                "postcode": listing.postcode,
                "asking_price": listing.asking_price,
                "property_type": listing.property_type,
                "bedrooms": listing.bedrooms,
                "tenure": listing.tenure,
                "floor_area_sqm": listing.floor_area_sqm,
                "floor_area_source": getattr(listing, "floor_area_source", ""),
                "override_street_name": listing.override_street_name,
            },
            "evidence": ev.to_dict(),
        }
        elapsed = time.time() - start
        print(f"  Done ({elapsed:.0f}s) — {ev.total_scored} scored comps", flush=True)
    except Exception as e:
        print(f"  ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

CACHE_PATH.write_text(json.dumps(cache, default=str), encoding="utf-8")
print(f"\nSaved cache to {CACHE_PATH} ({len(cache)} properties)", flush=True)
