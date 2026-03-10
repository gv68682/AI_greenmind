import requests
import streamlit as st



def build_tools(vectordb_1, vectordb_2):
    from langchain_core.tools import StructuredTool        # ← move here
    from langchain_community.vectorstores import FAISS
    from pydantic import BaseModel, Field
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    # Schema for air quality tool
    class AirQualityInput(BaseModel):
        location: str = Field(
            description="City, state or country name. Example: 'Delhi', 'New York', 'Germany'"
        )
    class ClimateInput(BaseModel):
        location: str = Field(
            description="City, state or country name. Example: 'Mumbai', 'Brazil', 'Kenya'"
        )
    class BiodiversityInput(BaseModel):
        query: str = Field(
            description="ISO 2-letter country code, optionally with year range. Examples: 'IN', 'BR,2015,2024', 'US,2000,2024'"
        )
    class SearchInput(BaseModel):
        query: str = Field(
            description="Search query for current environmental news and policies"
        )
    class RAGInput(BaseModel):
        query: str = Field(
            description="Question to search in environmental documents"
        )
        

    def get_coordinates(location: str) -> tuple[float, float]:
        """Convert any location name to latitude/longitude."""
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": location, "count": 1, "language": "en", "format": "json"}
        res = requests.get(url, params=params).json()
        results = res.get("results", [])
        if not results:
            raise ValueError(f"Location '{location}' not found.")
        return results[0]["latitude"], results[0]["longitude"]


    # ─────────────────────────────────────────
    # RAG Tool 1
    # ─────────────────────────────────────────
    def _rag_policies(query: str) -> str:
        results = vectordb_1.similarity_search(query, k=8)
        if not results:
            return "No relevant information found in environmental policy documents."
        context = "\n\n".join([doc.page_content for doc in results])
        return (
            f"RETRIEVED SCIENTIFIC EVIDENCE [ANSWER ONLY FROM THIS]:\n\n"
            f"{context}\n\n"
            f"INSTRUCTION: You MUST base your answer entirely on the above "
            f"retrieved content. Do NOT say you lack information."
        )

    rag_tool_environmental_policies = StructuredTool.from_function(
        func=_rag_policies,
        name="rag_tool_environmental_policies",
        description="Use for questions about environmental policies, international agreements, regulatory frameworks, authority actions, compliance procedures.",
        args_schema=RAGInput
    )


    # ─────────────────────────────────────────
    # RAG Tool 2
    # ─────────────────────────────────────────
    def _rag_effects(query: str) -> str:
        results = vectordb_2.similarity_search(query, k=8)

        # ✅ debug prints here — inside the function
        print(f"DEBUG RAG EFFECTS — query    : {query}")
        print(f"DEBUG RAG EFFECTS — retrieved: {len(results)}")
        for i, doc in enumerate(results):
            print(f"  [{i}] {doc.page_content[:100]}")

        if not results:
            return "No relevant information found in environmental effects documents."
        context = "\n\n".join([doc.page_content for doc in results])
        return (
            f"RETRIEVED SCIENTIFIC EVIDENCE [ANSWER ONLY FROM THIS]:\n\n"
            f"{context}\n\n"
            f"INSTRUCTION: You MUST base your answer entirely on the above "
            f"retrieved content. Do NOT say you lack information."
        )
    

    rag_tool_environmental_effects = StructuredTool.from_function(
        func=_rag_effects,
        name="rag_tool_environmental_effects",
        description="Use for questions about environmental degradation, causes, effects on ecosystems, biodiversity, human health. Sources: IPCC, UNEP, WHO, FAO.",
        args_schema=RAGInput
    )


    # ─────────────────────────────────────────
    # Search Tool
    # ─────────────────────────────────────────
    def _search(query: str) -> str:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append(
                    f"{r['title']}\n{r['body']}\nSource: {r['href']}"
                )
        return "\n\n".join(results) if results else "No results found."

    search_tool = StructuredTool.from_function(
        func=_search,
        name="search_tool",
        description="Search web for current environmental news, recent authority actions, latest policy updates 2024-2026 not in PDF documents.",
        args_schema=SearchInput
    )

    # ─────────────────────────────────────────
    # Air Quality Tool
    # ─────────────────────────────────────────
    def _air_quality(location: str) -> str:
        import requests
        lat, lon = get_coordinates(location)
        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params = {
            "latitude":      lat,
            "longitude":     lon,
            "current":       ["pm10", "pm2_5", "us_aqi", "european_aqi",
                            "nitrogen_dioxide", "ozone",
                            "sulphur_dioxide", "carbon_monoxide"],
            "hourly":        ["pm2_5", "us_aqi", "pm10",
                            "nitrogen_dioxide", "ozone"],
            "forecast_days": 7
        }

        res  = requests.get(url, params=params).json()
        curr = res.get("current", {})
        # ─────────────────────────────────────────
        # DEBUG — print raw API response to terminal
        # ─────────────────────────────────────────
        print("DEBUG RAW API RESPONSE:")
        print(res.keys())
        print("hourly keys:", res.get("hourly", {}).keys())
        print("hourly times sample:", res.get("hourly", {}).get("time", [])[:5])
        print("hourly aqi sample:", res.get("hourly", {}).get("us_aqi", [])[:5])
        print("hourly pm25 sample:", res.get("hourly", {}).get("pm2_5", [])[:5])

        aqi = curr.get("us_aqi", 0)
        if   aqi <= 50:  category = "Good 🟢"
        elif aqi <= 100: category = "Moderate 🟡"
        elif aqi <= 150: category = "Unhealthy for Sensitive Groups 🟠"
        elif aqi <= 200: category = "Unhealthy 🔴"
        elif aqi <= 300: category = "Very Unhealthy 🟣"
        else:            category = "Hazardous ⚫"

        # Extract daily forecast
        hourly       = res.get("hourly", {})
        times        = hourly.get("time", [])
        aqi_hourly   = hourly.get("us_aqi", [])
        pm25_hourly  = hourly.get("pm2_5", [])
        pm10_hourly  = hourly.get("pm10", [])
        no2_hourly   = hourly.get("nitrogen_dioxide", [])
        ozone_hourly = hourly.get("ozone", [])

        daily_forecast = {}
        for i, t in enumerate(times):
            if "T12:00" in t:
                date = t.split("T")[0]
                daily_forecast[date] = {
                    "aqi":   aqi_hourly[i]   if i < len(aqi_hourly)   else "N/A",
                    "pm25":  pm25_hourly[i]  if i < len(pm25_hourly)  else "N/A",
                    "pm10":  pm10_hourly[i]  if i < len(pm10_hourly)  else "N/A",
                    "no2":   no2_hourly[i]   if i < len(no2_hourly)   else "N/A",
                    "ozone": ozone_hourly[i] if i < len(ozone_hourly) else "N/A",
                }

        forecast_lines = ""
        for date, data in daily_forecast.items():
            day_aqi = data["aqi"] or 0
            if   day_aqi <= 50:  day_cat = "Good 🟢"
            elif day_aqi <= 100: day_cat = "Moderate 🟡"
            elif day_aqi <= 150: day_cat = "Unhealthy for Sensitive 🟠"
            elif day_aqi <= 200: day_cat = "Unhealthy 🔴"
            elif day_aqi <= 300: day_cat = "Very Unhealthy 🟣"
            else:                day_cat = "Hazardous ⚫"

            forecast_lines += (
                f"DATE:{date} | AQI:{day_aqi} | CATEGORY:{day_cat} | "
                f"PM2.5:{data['pm25']}µg/m³ | PM10:{data['pm10']}µg/m³ | "
                f"NO2:{data['no2']}µg/m³ | OZONE:{data['ozone']}µg/m³\n"
            )

        # ─────────────────────────────────────────
        # ✅ KEY FIX: Label data as MANDATORY
        # so Gemini cannot summarize or skip it
        # ─────────────────────────────────────────
        return f"""
            CURRENT_AIR_QUALITY_DATA [MANDATORY - DISPLAY ALL]:
            LOCATION     : {location}
            US_AQI       : {curr.get('us_aqi')} — {category}
            EUROPEAN_AQI : {curr.get('european_aqi')}
            PM2.5        : {curr.get('pm2_5')} µg/m³
            PM10         : {curr.get('pm10')} µg/m³
            NO2          : {curr.get('nitrogen_dioxide')} µg/m³
            OZONE        : {curr.get('ozone')} µg/m³
            SO2          : {curr.get('sulphur_dioxide')} µg/m³
            CO           : {curr.get('carbon_monoxide')} µg/m³

            7_DAY_FORECAST_DATA [MANDATORY - DISPLAY ALL 7 DAYS]:
            {forecast_lines}
            INSTRUCTION: You MUST display every single day
            of the 7_DAY_FORECAST_DATA above in your response.
            Do NOT summarize. Do NOT say forecast is available.
            Show ALL dates and ALL numbers listed above.
            """


    air_quality_tool = StructuredTool.from_function(
        func=_air_quality,
        name="air_quality_tool",
        description="Get present real-time AQI and 7-day pollution forecast for any country, state or city. Use for current pollution levels and short-term forecast.",
        args_schema=AirQualityInput
    )

    # ─────────────────────────────────────────
    # Climate Projection Tool
    # ─────────────────────────────────────────
    def _climate(location: str) -> str:
 
        lat, lon = get_coordinates(location)
        url = "https://climate-api.open-meteo.com/v1/climate"
        params = {
            "latitude":   lat,
            "longitude":  lon,
            "start_date": "2024-01-01",
            "end_date":   "2050-12-31",
            "models":     "CMIP6",
            "daily":      ["temperature_2m_max", "temperature_2m_min",
                        "precipitation_sum"]
        }
        res   = requests.get(url, params=params).json()

        # ─────────────────────────────────────────
        # DEBUG — check what API returns
        # ─────────────────────────────────────────
        print("DEBUG CLIMATE — keys    :", res.keys())
        print("DEBUG CLIMATE — daily   :", list(res.get("daily", {}).keys()))
        print("DEBUG CLIMATE — times   :", res.get("daily", {}).get("time", [])[:3])
        print("DEBUG CLIMATE — temp_max:", res.get("daily", {}).get("temperature_2m_max", [])[:3])

        daily    = res.get("daily", {})
        times    = daily.get("time", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        precip   = daily.get("precipitation_sum",  [])

        # ─────────────────────────────────────────
        # Check if data actually returned
        # ─────────────────────────────────────────
        if not times:
            return f"❌ No climate projection data returned for {location}"

        snapshots = {}
        for year in [2025, 2030, 2040, 2050]:
            for i, t in enumerate(times):
                if t.startswith(str(year)):
                    snapshots[year] = {
                        "temp_max": temp_max[i] if temp_max else "N/A",
                        "temp_min": temp_min[i] if temp_min else "N/A",
                        "precip":   precip[i]   if precip   else "N/A",
                    }
                    break

        if not snapshots:
            return f"❌ Could not extract yearly snapshots for {location}"

        result = f"🌍 Climate Projections — {location} (CMIP6)\n"
        for year, data in snapshots.items():
            result += f"📅 {year}: Max {data['temp_max']}°C | Min {data['temp_min']}°C | Precip {data['precip']}mm\n"

        return result


    climate_projection_tool = StructuredTool.from_function(
        func=_climate,
        name="climate_projection_tool",
        description="Get long-term climate projections up to 2050 for any location using CMIP6 models. Use for future climate forecast, temperature and precipitation projections.",
        args_schema=ClimateInput
    )

    # ─────────────────────────────────────────
    # Biodiversity Tool
    # ─────────────────────────────────────────
    def _biodiversity(query: str) -> str:
        import requests
        parts        = [p.strip() for p in query.split(",")]
        country_code = parts[0].upper()
        start_year   = parts[1] if len(parts) > 1 else "2020"
        end_year     = parts[2] if len(parts) > 2 else "2024"
        url    = "https://api.gbif.org/v1/occurrence/search"
        params = {
            "country": country_code,
            "year":    f"{start_year},{end_year}",
            "limit":   10
        }
        res     = requests.get(url, params=params).json()
        count   = res.get("count", 0)
        results = res.get("results", [])
        species_list = [
            f"• {r.get('scientificName','Unknown')} (Kingdom: {r.get('kingdom','Unknown')}, Year: {r.get('year','Unknown')})"
            for r in results
        ]
        species_text = "\n".join(species_list) if species_list else "No species data found."
        return f"""
            🌿 Biodiversity — {country_code} ({start_year}–{end_year})
            Total Records : {count:,}
            Sample Species:
            {species_text}
        """

    biodiversity_tool = StructuredTool.from_function(
        func=_biodiversity,
        name="biodiversity_tool",
        description="Get biodiversity and species data for any country. Input MUST be ISO 2-letter country code. Examples: 'IN', 'BR,2015,2024', 'US,2000,2024'. Brazil=BR, India=IN, USA=US, Germany=DE, Kenya=KE, China=CN.",
        args_schema=BiodiversityInput
    )

    return [
        rag_tool_environmental_effects,
        rag_tool_environmental_policies,
        search_tool,
        air_quality_tool,
        climate_projection_tool,
        biodiversity_tool
    ]


# ─────────────────────────────────────────────
# Streamlit cached wrapper
# ─────────────────────────────────────────────
@st.cache_resource
def build_tools_cached(_vectordb_1, _vectordb_2):
    return build_tools(_vectordb_1, _vectordb_2)