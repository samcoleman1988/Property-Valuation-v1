"""Parse property details from a single Rightmove listing URL.

This module only processes the individual listing page the user provides.
It does NOT scrape search results or crawl multiple pages.
"""

import re
import json
from typing import Optional
from dataclasses import dataclass, field, asdict

import requests
from bs4 import BeautifulSoup

from .utils import extract_postcode, safe_float, safe_int


@dataclass
class PropertyListing:
    url: str = ""
    rightmove_id: str = ""
    asking_price: float = 0.0
    price_qualifier: str = ""
    address: str = ""
    postcode: str = ""
    property_type: str = ""
    bedrooms: int = 0
    bathrooms: int = 0
    receptions: int = 0
    tenure: str = ""
    floor_area_sqft: float = 0.0
    floor_area_sqm: float = 0.0
    floor_area_source: str = ""
    epc_rating: str = ""
    description: str = ""
    agent_name: str = ""
    agent_phone: str = ""
    key_features: list = field(default_factory=list)
    photo_urls: list = field(default_factory=list)
    floorplan_urls: list = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    date_listed: str = ""
    council_tax_band: str = ""
    extraction_warnings: list = field(default_factory=list)

    # --- Manual identity overrides (user-supplied, not from Rightmove) ---
    override_house_number: str = ""
    override_building_name: str = ""
    override_street_name: str = ""
    override_postcode: str = ""
    override_property_name: str = ""
    override_estate_name: str = ""
    overrides_applied: list = field(default_factory=list)

    @property
    def effective_postcode(self) -> str:
        return self.override_postcode or self.postcode

    @property
    def effective_street(self) -> str:
        if self.override_street_name:
            return self.override_street_name
        if self.address:
            parts = self.address.split(",")
            if parts:
                import re
                raw = parts[0].strip()
                return re.sub(r"^\d+[a-zA-Z]?\s*", "", raw).strip()
        return ""

    @property
    def effective_address_first_line(self) -> str:
        parts = []
        if self.override_house_number:
            parts.append(self.override_house_number)
        if self.override_building_name:
            parts.append(self.override_building_name)
        if self.override_street_name:
            parts.append(self.override_street_name)
        if parts:
            return " ".join(parts)
        if self.address:
            return self.address.split(",")[0].strip()
        return ""

    def to_dict(self) -> dict:
        return asdict(self)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def extract_rightmove_id(url: str) -> str:
    match = re.search(r"properties/(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"property-(\d+)", url)
    if match:
        return match.group(1)
    return ""


def parse_listing(url: str) -> PropertyListing:
    """Fetch and parse a single Rightmove listing page.

    Returns a PropertyListing with as many fields populated as possible.
    Fields that cannot be extracted are left at defaults and a warning is added.
    """
    listing = PropertyListing(url=url)
    listing.rightmove_id = extract_rightmove_id(url)

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        listing.extraction_warnings.append(f"Failed to fetch page: {e}")
        return listing

    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    _parse_json_ld(soup, listing)
    _parse_window_data(html, listing)
    _parse_html_fallback(soup, listing)
    _validate(listing)

    return listing


def _parse_json_ld(soup: BeautifulSoup, listing: PropertyListing):
    """Extract data from JSON-LD structured data if present."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") in ("Product", "Residence", "SingleFamilyResidence", "House", "Apartment"):
                if "name" in data:
                    listing.address = listing.address or data["name"]
                if "offers" in data:
                    offers = data["offers"]
                    if isinstance(offers, list):
                        offers = offers[0]
                    listing.asking_price = listing.asking_price or safe_float(offers.get("price"))
                if "geo" in data:
                    listing.latitude = listing.latitude or safe_float(data["geo"].get("latitude"))
                    listing.longitude = listing.longitude or safe_float(data["geo"].get("longitude"))
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue


def _unpack_model(data: dict) -> dict:
    """Unpack Rightmove's packed array format into a plain dict.

    The packed format stores a JSON string in data["data"] containing an array
    where element 0 is a schema (keys map to array indices) and subsequent
    elements are the values. This recursively resolves indices to values.
    """
    raw = data.get("data")
    if not isinstance(raw, str):
        return data

    try:
        arr = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return data

    if not isinstance(arr, list) or len(arr) < 2:
        return data

    def resolve(obj):
        if isinstance(obj, dict):
            return {k: resolve(v) for k, v in obj.items()}
        if isinstance(obj, int) and 0 <= obj < len(arr):
            val = arr[obj]
            if isinstance(val, dict):
                return resolve(val)
            if isinstance(val, list):
                return [resolve(item) for item in val]
            return val
        if isinstance(obj, list):
            return [resolve(item) for item in obj]
        return obj

    schema = arr[0]
    if not isinstance(schema, dict):
        return data

    return resolve(schema)


def _parse_window_data(html: str, listing: PropertyListing):
    """Extract data from Rightmove's embedded JavaScript window.PAGE_MODEL or similar."""
    # Try new packed format first: window.__PAGE_MODEL
    match = re.search(
        r"window\.__PAGE_MODEL\s*=\s*(.*?)\s*;\s*</script>", html, re.DOTALL
    )
    if match:
        raw = match.group(1).strip()
        # Find the end of the top-level JSON object by bracket matching
        depth = 0
        end = -1
        for i, c in enumerate(raw):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > 0:
            try:
                packed = json.loads(raw[:end])
                unpacked = _unpack_model(packed)
                prop = unpacked.get("propertyData", {})
                if isinstance(prop, dict) and prop:
                    _apply_prop_data(prop, listing)
                    return
            except (json.JSONDecodeError, TypeError, RecursionError):
                pass

    # Fall back to old format: window.PAGE_MODEL
    match = re.search(
        r"window\.PAGE_MODEL\s*=\s*(\{.*?\})\s*;?\s*</script>", html, re.DOTALL
    )
    if not match:
        match = re.search(
            r"window\.PAGE_MODEL\s*=\s*(\{.*?\})\s*$", html, re.MULTILINE | re.DOTALL
        )
    if not match:
        return

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        raw = match.group(1)
        for end_pos in [raw.rfind("}}")]:
            if end_pos > 0:
                try:
                    data = json.loads(raw[: end_pos + 2])
                    break
                except json.JSONDecodeError:
                    continue
        else:
            return

    prop = data.get("propertyData", {})
    if not prop:
        return
    _apply_prop_data(prop, listing)


def _apply_prop_data(prop: dict, listing: PropertyListing):
    """Apply parsed propertyData fields to the listing."""

    prices = prop.get("prices", {})
    if isinstance(prices, dict):
        raw_price = prices.get("primaryPrice", "")
        if isinstance(raw_price, str):
            raw_price = raw_price.replace("£", "").replace(",", "")
        listing.asking_price = listing.asking_price or safe_float(raw_price)
        listing.price_qualifier = listing.price_qualifier or prices.get("displayPriceQualifier", "") or prices.get("priceQualifier", "")

    addr = prop.get("address", {})
    if addr:
        display = addr.get("displayAddress", "")
        listing.address = listing.address or display
        listing.postcode = listing.postcode or addr.get("outcode", "") + " " + addr.get("incode", "")
        listing.postcode = listing.postcode.strip()

    listing.property_type = listing.property_type or prop.get("propertySubType", "") or prop.get("propertyType", "")
    listing.bedrooms = listing.bedrooms or safe_int(prop.get("bedrooms"))
    listing.bathrooms = listing.bathrooms or safe_int(prop.get("bathrooms"))
    listing.receptions = listing.receptions or safe_int(prop.get("receptions"))

    # Tenure
    tenure_info = prop.get("tenure", {})
    if isinstance(tenure_info, dict):
        listing.tenure = listing.tenure or tenure_info.get("tenureType", "")
    elif isinstance(tenure_info, str):
        listing.tenure = listing.tenure or tenure_info
    # Normalise: FREEHOLD -> Freehold, LEASEHOLD -> Leasehold
    if listing.tenure:
        tenure_map = {
            "FREEHOLD": "Freehold",
            "LEASEHOLD": "Leasehold",
            "SHARE_OF_FREEHOLD": "Share of Freehold",
            "COMMONHOLD": "Commonhold",
        }
        listing.tenure = tenure_map.get(listing.tenure.upper(), listing.tenure.title())

    # Floor area
    sizes = prop.get("sizings", [])
    if sizes:
        for s in sizes:
            unit = s.get("unit", "")
            val = safe_float(s.get("minimumSize") or s.get("maximumSize"))
            if "sq. ft" in unit.lower() or "sqft" in unit.lower():
                listing.floor_area_sqft = listing.floor_area_sqft or val
            elif "sq. m" in unit.lower() or "sqm" in unit.lower():
                listing.floor_area_sqm = listing.floor_area_sqm or val

    if listing.floor_area_sqft and not listing.floor_area_sqm:
        listing.floor_area_sqm = round(listing.floor_area_sqft * 0.092903, 1)
    elif listing.floor_area_sqm and not listing.floor_area_sqft:
        listing.floor_area_sqft = round(listing.floor_area_sqm * 10.7639, 1)

    if listing.floor_area_sqm > 0 and not listing.floor_area_source:
        listing.floor_area_source = "Rightmove"

    # EPC
    epc = prop.get("epc", {})
    if epc:
        listing.epc_rating = listing.epc_rating or epc.get("currentEnergyRating", "")

    # Key features
    listing.key_features = listing.key_features or prop.get("keyFeatures", [])

    # Description
    listing.description = listing.description or prop.get("text", {}).get("description", "")

    # Agent
    agent = prop.get("customer", {})
    listing.agent_name = listing.agent_name or agent.get("branchDisplayName", "")
    listing.agent_phone = listing.agent_phone or agent.get("contactTelephone", "")

    # Location
    loc = prop.get("location", {})
    listing.latitude = listing.latitude or safe_float(loc.get("latitude"))
    listing.longitude = listing.longitude or safe_float(loc.get("longitude"))

    # Photos
    if not listing.photo_urls:
        images = prop.get("images", [])
        listing.photo_urls = [img.get("url", "") or img.get("srcUrl", "") for img in images if img.get("url") or img.get("srcUrl")]

    # Floorplans
    if not listing.floorplan_urls:
        fps = prop.get("floorplans", [])
        listing.floorplan_urls = [fp.get("url", "") or fp.get("srcUrl", "") for fp in fps if fp.get("url") or fp.get("srcUrl")]

    # Listing date
    listing_history = prop.get("listingHistory", {})
    if isinstance(listing_history, dict):
        listing.date_listed = listing.date_listed or listing_history.get("listingUpdateReason", "")
    listing_update = prop.get("listingUpdate", {})
    if isinstance(listing_update, dict):
        listing.date_listed = listing.date_listed or listing_update.get("listingUpdateDate", "")

    # Council tax — may be top-level or under livingCosts
    listing.council_tax_band = listing.council_tax_band or prop.get("councilTaxBand", "")
    if not listing.council_tax_band:
        living = prop.get("livingCosts", {})
        if isinstance(living, dict):
            listing.council_tax_band = living.get("councilTaxBand", "")


def _parse_html_fallback(soup: BeautifulSoup, listing: PropertyListing):
    """Fallback: scrape visible HTML elements when JS data is unavailable."""
    # Price
    if not listing.asking_price:
        price_el = soup.find("span", {"data-testid": "price"}) or soup.find("p", class_=re.compile(r"price", re.I))
        if price_el:
            listing.asking_price = safe_float(price_el.get_text())

    # Address
    if not listing.address:
        addr_el = soup.find("h1", {"itemprop": "streetAddress"}) or soup.find("meta", {"property": "og:title"})
        if addr_el:
            listing.address = addr_el.get_text(strip=True) if hasattr(addr_el, "get_text") else addr_el.get("content", "")

    # Postcode from address
    if not listing.postcode and listing.address:
        listing.postcode = extract_postcode(listing.address) or ""

    # Description
    if not listing.description:
        desc_el = soup.find("div", {"data-testid": "truncated_description"}) or soup.find("div", class_=re.compile(r"description", re.I))
        if desc_el:
            listing.description = desc_el.get_text(separator=" ", strip=True)

    # Key features from list items
    if not listing.key_features:
        kf_section = soup.find("ul", class_=re.compile(r"keyfeature", re.I))
        if kf_section:
            listing.key_features = [li.get_text(strip=True) for li in kf_section.find_all("li")]


def _validate(listing: PropertyListing):
    """Add warnings for missing critical fields."""
    if not listing.asking_price:
        listing.extraction_warnings.append("Could not extract asking price")
    if not listing.address and not listing.postcode:
        listing.extraction_warnings.append("Could not extract address or postcode")
    if not listing.postcode and listing.address:
        listing.postcode = extract_postcode(listing.address) or ""
        if not listing.postcode:
            listing.extraction_warnings.append("Could not extract postcode from address")
    if not listing.property_type:
        listing.extraction_warnings.append("Could not determine property type")
    if not listing.bedrooms:
        listing.extraction_warnings.append("Could not determine number of bedrooms")
    if not listing.floor_area_sqft:
        listing.extraction_warnings.append("No floor area available — valuation per sqft will be unavailable")
