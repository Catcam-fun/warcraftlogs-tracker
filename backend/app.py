#!/usr/bin/env python3
"""
WarcraftLogs API Audit Tool

Directly queries WarcraftLogs API to verify backend is fetching and processing all deaths correctly.
This checks for:
- Missing reports
- Missing pulls
- Missing deaths in backend data
- Data handling issues

Usage:
  python wcl_audit.py --client-id <id> --client-secret <secret> --guild "Do Over" --server "Thrall" --region "us"
"""

import requests
import json
import sys
import argparse
from collections import defaultdict
from datetime import datetime
import time

# Constants from your backend
MASS_DEATH_THRESHOLD = 7
MASS_DEATH_WINDOW = 10000  # ms

# WarcraftLogs API endpoints (through your Cloudflare proxy)
GRAPHQL_ENDPOINT = "https://wcl-proxy.catcam-fun.workers.dev/api/v2/client"
OAUTH_TOKEN_URL = "https://wcl-proxy.catcam-fun.workers.dev/oauth/token"

class WCLAuditor:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        
    def get_access_token(self):
        """Get OAuth2 access token"""
        if self.token:
            return self.token
            
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        try:
            response = requests.post(OAUTH_TOKEN_URL, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()
            self.token = token_data["access_token"]
            return self.token
        except Exception as e:
            raise Exception(f"Failed to get access token: {str(e)}")
    
    def graphql_query(self, query, variables=None):
        """Execute a GraphQL query"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        
        try:
            response = requests.post(GRAPHQL_ENDPOINT, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            if "errors" in data:
                raise Exception(f"GraphQL errors: {data['errors']}")
            
            return data.get("data", {})
        except Exception as e:
            raise Exception(f"GraphQL query failed: {str(e)}")
    
    def get_guild_reports(self, guild_name, server, region, zone_id, cutoff_date):
        """Fetch all reports for guild in zone"""
        print(f"\n📊 Fetching reports for {guild_name}-{server} ({region}) in zone {zone_id}...")
        
        cutoff_ts = int(datetime.strptime(cutoff_date, "%Y-%m-%d").timestamp() * 1000) + 86400000 - 1
        
        query = """
        query($guildName: String!, $serverSlug: String!, $serverRegion: String!, $zoneID: Int!) {
          reportData {
            reports(guildName: $guildName, guildServerSlug: $serverSlug, guildServerRegion: $serverRegion, zoneID: $zoneID, limit: 100) {
              data {
                code
                startTime
                endTime
                zone {
                  id
                }
                owner {
                  name
                }
              }
            }
          }
        }
        """
        
        variables = {
            "guildName": guild_name,
            "serverSlug": server.lower().replace(" ", "-").replace("'", ""),
            "serverRegion": region.upper(),
            "zoneID": int(zone_id)
        }
        
        data = self.graphql_query(query, variables)
        reports_data = data.get("reportData", {}).get("reports", {}).get("data", [])
        
        reports = []
        for rep in reports_data:
            if rep.get("startTime", 0) <= cutoff_ts:
                reports.append({
                    "code": rep["code"],
                    "start": rep.get("startTime", 0),
                    "end": rep.get("endTime", 0),
                    "owner": rep.get("owner", {}).get("name", "")
                })
        
        print(f"✓ Found {len(reports)} reports")
        return reports
    
    def get_report_fights(self, report_code, fight_zone, difficulty):
        """Fetch fights from a report"""
        query = """
        query($code: String!) {
          reportData {
            report(code: $code) {
              startTime
              fights {
                id
                startTime
                endTime
                name
                encounterID
                difficulty
                kill
                gameZone {
                  id
                }
              }
              masterData {
                actors(type: "Player") {
                  id
                  name
                }
              }
            }
          }
        }
        """
        
        variables = {"code": report_code}
        data = self.graphql_query(query, variables)
        report = data.get("reportData", {}).get("report", {})
        
        if not report:
            return [], [], 0
        
        report_start = report.get("startTime", 0)
        fights = report.get("fights", [])
        actors = report.get("masterData", {}).get("actors", [])
        
        # Filter to matching zone and difficulty
        matching_fights = []
        for fight in fights:
            if fight.get("encounterID") and fight.get("encounterID") != 0:
                zone_id = fight.get("gameZone", {}).get("id")
                fight_difficulty = fight.get("difficulty")
                
                if zone_id == int(fight_zone) and fight_difficulty == int(difficulty):
                    matching_fights.append({
                        "id": fight["id"],
                        "start_time": fight["startTime"],
                        "end_time": fight["endTime"],
                        "name": fight.get("name", "Unknown"),
                        "encounterID": fight["encounterID"],
                        "kill": fight.get("kill", False)
                    })
        
        # Build actor map
        actor_map = {}
        for actor in actors:
            actor_map[actor["id"]] = actor["name"]
        
        return matching_fights, actor_map, report_start
    
    def get_report_deaths(self, report_code, fights, actor_map):
        """Fetch all deaths for fights in a report"""
        if not fights:
            return {}
        
        start_time = min(f['start_time'] for f in fights)
        end_time = max(f['end_time'] for f in fights)
        
        query = """
        query($code: String!, $startTime: Float!, $endTime: Float!) {
          reportData {
            report(code: $code) {
              deaths: events(
                startTime: $startTime
                endTime: $endTime
                dataType: Deaths
                limit: 10000
              ) {
                data
              }
            }
          }
        }
        """
        
        variables = {
            "code": report_code,
            "startTime": start_time,
            "endTime": end_time
        }
        
        data = self.graphql_query(query, variables)
        death_events = data.get("reportData", {}).get("report", {}).get("deaths", {}).get("data", [])
        
        # Group deaths by fight
        deaths_by_fight = defaultdict(list)
        
        for event in death_events:
            timestamp = event.get("timestamp")
            target_id = event.get("targetID")
            ability_id = event.get("abilityGameID")
            
            if not target_id or timestamp is None:
                continue
            
            player_name = actor_map.get(target_id)
            if not player_name:
                continue
            
            # Find which fight this death belongs to
            for fight in fights:
                if fight['start_time'] <= timestamp <= fight['end_time']:
                    deaths_by_fight[fight['id']].append({
                        "timestamp": timestamp,
                        "player": player_name,
                        "ability_id": ability_id
                    })
                    break
        
        return deaths_by_fight
    
    def audit_guild(self, guild_name, server, region, zone_id, fight_zone, difficulty, cutoff_date, backend_data_path=None):
        """
        Comprehensive audit of guild data
        
        Args:
            backend_data_path: Path to exported backend data (optional)
        """
        print("=" * 80)
        print("WARCRAFTLOGS API AUDIT")
        print("=" * 80)
        print(f"Guild: {guild_name}-{server} ({region})")
        print(f"Zone: {zone_id} (fight zone: {fight_zone}, difficulty: {difficulty})")
        print(f"Cutoff date: {cutoff_date}")
        print()
        
        # Get token
        self.get_access_token()
        
        # Fetch reports from WCL
        reports = self.get_guild_reports(guild_name, server, region, zone_id, cutoff_date)
        
        if not reports:
            print("❌ No reports found!")
            return
        
        # Process each report
        print(f"\n📥 Processing {len(reports)} reports...")
        
        wcl_data = {
            "reports": {},
            "total_pulls": 0,
            "total_deaths": 0,
            "pulls_by_boss": defaultdict(int),
            "deaths_by_player": defaultdict(int)
        }
        
        for idx, report in enumerate(reports, 1):
            report_code = report["code"]
            print(f"\n[{idx}/{len(reports)}] Processing report {report_code}...")
            
            # Get fights
            fights, actor_map, report_start = self.get_report_fights(report_code, fight_zone, difficulty)
            
            if not fights:
                print(f"  No matching fights in this report")
                continue
            
            print(f"  Found {len(fights)} matching fights")
            
            # Get deaths
            deaths_by_fight = self.get_report_deaths(report_code, fights, actor_map)
            
            report_total_deaths = sum(len(deaths) for deaths in deaths_by_fight.values())
            print(f"  Found {report_total_deaths} total deaths")
            
            # Store
            wcl_data["reports"][report_code] = {
                "fights": fights,
                "deaths_by_fight": deaths_by_fight,
                "report_start": report_start
            }
            
            wcl_data["total_pulls"] += len(fights)
            wcl_data["total_deaths"] += report_total_deaths
            
            for fight in fights:
                wcl_data["pulls_by_boss"][fight["name"]] += 1
                
                fight_deaths = deaths_by_fight.get(fight["id"], [])
                for death in fight_deaths:
                    wcl_data["deaths_by_player"][death["player"]] += 1
            
            # Rate limit
            time.sleep(0.1)
        
        print("\n" + "=" * 80)
        print("WARCRAFTLOGS DATA SUMMARY")
        print("=" * 80)
        print(f"Total reports: {len(wcl_data['reports'])}")
        print(f"Total pulls: {wcl_data['total_pulls']}")
        print(f"Total deaths: {wcl_data['total_deaths']}")
        print(f"\nDeaths by boss:")
        for boss, count in sorted(wcl_data["pulls_by_boss"].items()):
            print(f"  {boss}: {count} pulls")
        print(f"\nTop 10 deaths by player:")
        top_players = sorted(wcl_data["deaths_by_player"].items(), key=lambda x: x[1], reverse=True)[:10]
        for player, count in top_players:
            print(f"  {player}: {count} deaths")
        
        # Compare with backend data if provided
        if backend_data_path:
            print("\n" + "=" * 80)
            print("COMPARING WITH BACKEND DATA")
            print("=" * 80)
            self.compare_with_backend(wcl_data, backend_data_path)
        
        # Save WCL audit data
        output_file = "wcl_audit_data.json"
        with open(output_file, 'w') as f:
            json.dump(wcl_data, f, indent=2, default=str)
        print(f"\n✓ WarcraftLogs audit data saved to: {output_file}")
        
        return wcl_data
    
    def compare_with_backend(self, wcl_data, backend_data_path):
        """Compare WCL data with backend processed data"""
        try:
            with open(backend_data_path, 'r') as f:
                backend_data = json.load(f)
        except Exception as e:
            print(f"❌ Could not load backend data: {e}")
            return
        
        raw_pulls = backend_data.get("rawPulls", [])
        
        print(f"\nBackend data:")
        print(f"  Pulls: {len(raw_pulls)}")
        
        # Compare reports
        wcl_reports = set(wcl_data["reports"].keys())
        backend_reports = set(pull["reportCode"] for pull in raw_pulls)
        
        missing_in_backend = wcl_reports - backend_reports
        extra_in_backend = backend_reports - wcl_reports
        
        print(f"\nReport comparison:")
        print(f"  WCL reports: {len(wcl_reports)}")
        print(f"  Backend reports: {len(backend_reports)}")
        if missing_in_backend:
            print(f"  ❌ Missing in backend: {len(missing_in_backend)}")
            for code in list(missing_in_backend)[:5]:
                print(f"     - {code}")
        if extra_in_backend:
            print(f"  ⚠️  Extra in backend: {len(extra_in_backend)}")
        if not missing_in_backend and not extra_in_backend:
            print(f"  ✓ All reports match!")
        
        # Compare pulls per report
        print(f"\nPull comparison by report:")
        for report_code in wcl_reports & backend_reports:
            wcl_fights = wcl_data["reports"][report_code]["fights"]
            backend_fights = [p for p in raw_pulls if p["reportCode"] == report_code]
            
            if len(wcl_fights) != len(backend_fights):
                print(f"  ❌ {report_code}: WCL has {len(wcl_fights)} pulls, backend has {len(backend_fights)}")
        
        # Compare total deaths
        print(f"\nDeath count comparison:")
        print(f"  WCL total deaths: {wcl_data['total_deaths']}")
        
        backend_total_deaths = sum(len(pull.get("deaths", [])) for pull in raw_pulls)
        print(f"  Backend total deaths: {backend_total_deaths}")
        
        if wcl_data['total_deaths'] != backend_total_deaths:
            diff = wcl_data['total_deaths'] - backend_total_deaths
            print(f"  ❌ Difference: {diff} deaths")
            if diff > 0:
                print(f"     Backend is MISSING {diff} deaths from WarcraftLogs!")
            else:
                print(f"     Backend has {abs(diff)} EXTRA deaths not in WarcraftLogs!")
        else:
            print(f"  ✓ Death counts match!")
        
        # Per-player comparison
        backend_deaths_by_player = defaultdict(int)
        for pull in raw_pulls:
            for death in pull.get("deaths", []):
                backend_deaths_by_player[death["name"]] += 1
        
        print(f"\nPer-player death comparison (top discrepancies):")
        discrepancies = []
        all_players = set(wcl_data["deaths_by_player"].keys()) | set(backend_deaths_by_player.keys())
        
        for player in all_players:
            wcl_count = wcl_data["deaths_by_player"].get(player, 0)
            backend_count = backend_deaths_by_player.get(player, 0)
            
            if wcl_count != backend_count:
                discrepancies.append((player, wcl_count, backend_count, wcl_count - backend_count))
        
        if discrepancies:
            discrepancies.sort(key=lambda x: abs(x[3]), reverse=True)
            print(f"  Found {len(discrepancies)} players with mismatched counts:")
            for player, wcl_count, backend_count, diff in discrepancies[:10]:
                status = "❌" if diff > 0 else "⚠️"
                print(f"  {status} {player}: WCL={wcl_count}, Backend={backend_count}, Diff={diff}")
        else:
            print(f"  ✓ All player death counts match!")

def main():
    parser = argparse.ArgumentParser(description="Audit WarcraftLogs data against backend")
    parser.add_argument("--client-id", required=True, help="WarcraftLogs client ID")
    parser.add_argument("--client-secret", required=True, help="WarcraftLogs client secret")
    parser.add_argument("--guild", required=True, help="Guild name")
    parser.add_argument("--server", required=True, help="Server name")
    parser.add_argument("--region", default="us", help="Region (default: us)")
    parser.add_argument("--zone", default="44", help="Report zone ID (default: 44)")
    parser.add_argument("--fight-zone", default="2810", help="Fight zone ID (default: 2810)")
    parser.add_argument("--difficulty", default="5", help="Difficulty (default: 5)")
    parser.add_argument("--cutoff-date", default="2025-10-10", help="Cutoff date (default: 2025-10-10)")
    parser.add_argument("--backend-data", help="Path to exported backend data JSON for comparison")
    
    args = parser.parse_args()
    
    auditor = WCLAuditor(args.client_id, args.client_secret)
    
    auditor.audit_guild(
        guild_name=args.guild,
        server=args.server,
        region=args.region,
        zone_id=args.zone,
        fight_zone=args.fight_zone,
        difficulty=args.difficulty,
        cutoff_date=args.cutoff_date,
        backend_data_path=args.backend_data
    )

if __name__ == "__main__":
    main()