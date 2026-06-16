#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deploy "Delivery Route Safety Net" watchdog to n8n.
Safeguard against the driver forgetting the "mission completed" action (or the
fire-and-forget mission-completed webhook silently failing): a daily 21:00 cron
that detects picked-up / at-workshop orders whose delivery is near (today..+2)
but have NO delivery route yet, then heals them by flipping status and calling
the existing mission-completed webhook (single route-creation authority), and
notifies the operator on Telegram.

Purely additive — does NOT modify MISSION_COMPLETED or DAILY_AUTO_ROUTE_CREATION.
Creates the workflow INACTIVE. UAT then activate separately.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import urllib.request
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = {}
for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        ENV[k] = v.strip().strip('"')

N8N_KEY = ENV["N8N_API_KEY"]
N8N_BASE = "https://n8n.k-sat.tech/api/v1"
SB_URL = ENV["SUPABASE_URL"].rstrip("/")
SB_KEY = ENV["SUPABASE_SERVICE_ROLE_KEY"]
REST = SB_URL + "/rest/v1"

# --- node helpers -----------------------------------------------------------
SB_HEADERS = {
    "parameters": [
        {"name": "apikey", "value": SB_KEY},
        {"name": "Authorization", "value": "Bearer " + SB_KEY},
    ]
}


def http_get(name, url, x, y):
    return {
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [x, y],
        "alwaysOutputData": True,
        "parameters": {
            "url": url,
            "sendHeaders": True,
            "headerParameters": SB_HEADERS,
            "options": {},
        },
    }


def code(name, js, x, y):
    return {
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [x, y],
        "parameters": {"jsCode": js},
    }


# --- 1. Schedule Trigger ----------------------------------------------------
n_trigger = {
    "name": "Schedule (21:00)",
    "type": "n8n-nodes-base.scheduleTrigger",
    "typeVersion": 1.3,
    "position": [0, 0],
    "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 21 * * *"}]}},
}

# --- 2. Compute Window ------------------------------------------------------
n_window = code(
    "Compute Window",
    "const d=new Date();const iso=x=>x.toISOString().split('T')[0];"
    "const p2=new Date(d);p2.setUTCDate(p2.getUTCDate()+2);"
    "return [{json:{today:iso(d),until:iso(p2)}}];",
    220, 0,
)

# --- 3. Get Stuck Candidates (route_stops join orders + pickup routes) -------
cand_url = (
    "=" + REST + "/route_stops?select=order_id,orders!inner(id,order_no,delivery_date,"
    "company_id,order_status,delivery_address,pickup_address),routes!inner(id,driver_id,route_type)"
    "&routes.route_type=eq.pickup&orders.order_status=in.(picked_up,at_workshop)"
    "&orders.delivery_date=gte.{{ $json.today }}&orders.delivery_date=lte.{{ $json.until }}"
)
n_cand = http_get("Get Stuck Candidates", cand_url, 440, 0)

# --- 4. Get Covered Delivery Stops (dedup source) ---------------------------
cov_url = (
    "=" + REST + "/route_stops?select=order_id,routes!inner(route_type,route_date)"
    "&routes.route_type=eq.delivery"
    "&routes.route_date=gte.{{ $('Compute Window').first().json.today }}"
    "&routes.route_date=lte.{{ $('Compute Window').first().json.until }}"
)
n_cov = http_get("Get Covered Delivery Stops", cov_url, 660, 0)

# --- 5. Build Heal Plan -----------------------------------------------------
heal_js = r"""
const cand=$('Get Stuck Candidates').all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]).filter(x=>x&&x.order_id&&x.orders&&x.routes);
const cov=$('Get Covered Delivery Stops').all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]).filter(x=>x&&x.order_id);
const covered=new Set(cov.map(c=>c.order_id));
const byOrder={};
for(const r of cand){
  if(covered.has(r.order_id)) continue;
  if(!byOrder[r.order_id]){
    byOrder[r.order_id]={order_id:r.order_id,status:r.orders.order_status,delivery_date:r.orders.delivery_date,
      driver_id:(r.routes&&r.routes.driver_id)||null,pickup_route_id:(r.routes&&r.routes.id)||null,order_no:r.orders.order_no};
  }
}
const stuck=Object.values(byOrder).filter(o=>o.pickup_route_id);
if(stuck.length===0){ return []; }
const driverCount={}; const pickupSet=new Set(); const allIds=[]; const pickedUp=[]; const dates={};
for(const s of stuck){
  driverCount[s.driver_id||'NONE']=(driverCount[s.driver_id||'NONE']||0)+1;
  pickupSet.add(s.pickup_route_id); allIds.push(s.order_id);
  if(s.status==='picked_up') pickedUp.push(s.order_id);
  const dd=s.delivery_date||'?'; dates[dd]=(dates[dd]||0)+1;
}
let driver=null,best=-1;
for(const k in driverCount){ if(k!=='NONE'&&driverCount[k]>best){best=driverCount[k];driver=k;} }
const routes=[...pickupSet].map(id=>({id:id,route_type:'pickup'}));
return [{json:{driver_id:driver,order_ids:allIds,all_picked_up_ids:pickedUp,routes:routes,
  dates:dates,total:allIds.length,picked_up_count:pickedUp.length,at_workshop_count:allIds.length-pickedUp.length}}];
"""
n_heal = code("Build Heal Plan", heal_js.strip(), 880, 0)

# --- 6. Flip Status (picked_up -> at_workshop, empty-guard dummy uuid) -------
flip_url = (
    "=" + REST + "/orders?order_status=eq.picked_up&id=in.("
    "{{ ($json.all_picked_up_ids && $json.all_picked_up_ids.length) ? "
    "$json.all_picked_up_ids.join(',') : '00000000-0000-0000-0000-000000000000' }})"
)
n_flip = {
    "name": "Flip Status to At Workshop",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [1100, 0],
    "alwaysOutputData": True,
    "parameters": {
        "method": "PATCH",
        "url": flip_url,
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "apikey", "value": SB_KEY},
                {"name": "Authorization", "value": "Bearer " + SB_KEY},
                {"name": "Content-Type", "value": "application/json"},
                {"name": "Prefer", "value": "return=representation"},
            ]
        },
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": '={{ {"order_status":"at_workshop","updated_at":$now.toISO()} }}',
        "options": {},
    },
}

# --- 7. Call MISSION (existing mission-completed webhook) --------------------
n_call = {
    "name": "Call Mission Completed",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [1320, 0],
    "alwaysOutputData": True,
    "parameters": {
        "method": "POST",
        "url": "https://n8n.k-sat.tech/webhook/mission-completed",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": '={{ {"driver_id":$(\'Build Heal Plan\').first().json.driver_id,'
                    '"order_ids":$(\'Build Heal Plan\').first().json.order_ids,'
                    '"routes":$(\'Build Heal Plan\').first().json.routes} }}',
        "options": {},
    },
}

# --- 8. Build Telegram text -------------------------------------------------
tg_js = r"""
const p=$('Build Heal Plan').first().json;
const dlist=Object.keys(p.dates||{}).map(d=>d+' ('+p.dates[d]+')').join(', ');
const txt='⚠️ Otomatik Teslimat Rotasi (Safety Net)\n\n'+
  'Sofor mission-completed yapmamis veya webhook dusmustu.\n'+
  'Iyilestirilen siparis: '+p.total+'\n'+
  '  - picked_up->at_workshop: '+p.picked_up_count+'\n'+
  '  - zaten at_workshop (webhook-fail): '+p.at_workshop_count+'\n'+
  'Teslimat tarihleri: '+dlist+'\n'+
  'Surucu: '+(p.driver_id||'-')+'\n'+
  'mission-completed tetiklendi; teslimat rotasi olusturuluyor.';
return [{json:{text:txt}}];
"""
n_tgbuild = code("Build Telegram Text", tg_js.strip(), 1540, 0)

# --- 9. Send Telegram -------------------------------------------------------
n_tgsend = {
    "name": "Send Telegram",
    "type": "n8n-nodes-base.telegram",
    "typeVersion": 1.2,
    "position": [1760, 0],
    "parameters": {
        "chatId": "5841852274",
        "text": "={{ $json.text }}",
        "additionalFields": {"appendAttribution": False},
    },
    "credentials": {"telegramApi": {"id": "CuNAjXFMgVToiCu0", "name": "Telegram account"}},
}

nodes = [n_trigger, n_window, n_cand, n_cov, n_heal, n_flip, n_call, n_tgbuild, n_tgsend]

connections = {
    "Schedule (21:00)": {"main": [[{"node": "Compute Window", "type": "main", "index": 0}]]},
    "Compute Window": {"main": [[{"node": "Get Stuck Candidates", "type": "main", "index": 0}]]},
    "Get Stuck Candidates": {"main": [[{"node": "Get Covered Delivery Stops", "type": "main", "index": 0}]]},
    "Get Covered Delivery Stops": {"main": [[{"node": "Build Heal Plan", "type": "main", "index": 0}]]},
    "Build Heal Plan": {"main": [[{"node": "Flip Status to At Workshop", "type": "main", "index": 0}]]},
    "Flip Status to At Workshop": {"main": [[{"node": "Call Mission Completed", "type": "main", "index": 0}]]},
    "Call Mission Completed": {"main": [[{"node": "Build Telegram Text", "type": "main", "index": 0}]]},
    "Build Telegram Text": {"main": [[{"node": "Send Telegram", "type": "main", "index": 0}]]},
}

workflow = {
    "name": "DELIVERY_ROUTE_SAFETY_NET",
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1", "timezone": "Europe/Brussels"},
}


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        N8N_BASE + path, data=data,
        headers={"X-N8N-API-KEY": N8N_KEY, "Content-Type": "application/json"},
        method=method,
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


if __name__ == "__main__":
    res = api("POST", "/workflows", workflow)
    print("CREATED id=", res.get("id"), "active=", res.get("active"), "nodes=", len(res.get("nodes", [])))
    print("NEXT: UAT with synthetic data, then POST /workflows/<id>/activate")
