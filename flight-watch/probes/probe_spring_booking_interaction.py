"""Official Spring flight search interaction probe using visible controls only."""
from playwright.sync_api import sync_playwright
import json
from datetime import datetime,timezone

def log(stage,data):
 print("OFFICIAL_STEP "+json.dumps({"stage":stage,"checked_at_utc":datetime.now(timezone.utc).isoformat(),"data":data},ensure_ascii=False),flush=True)
def scan(page):
 return page.evaluate("""() => ({
 url:location.href, body:(document.body?.innerText||'').slice(0,2500),
 inputs:[...document.querySelectorAll('input')].filter(e=>e.getBoundingClientRect().width>0).slice(0,22).map(e=>({name:e.name,value:e.value,placeholder:e.placeholder,data_code:e.getAttribute('data-code'),data_citycode:e.getAttribute('data-citycode')})),
 popups:[...document.querySelectorAll('li,.city-item,.searchCityList,.citySelect,.date-item,.calendar td')].filter(e=>e.getBoundingClientRect().width>0).slice(0,35).map(e=>({tag:e.tagName,cls:String(e.className).slice(0,90),text:(e.innerText||'').slice(0,80)}))
 })""")
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 page=b.new_page(viewport={"width":1440,"height":900},locale="zh-CN")
 try:
  page.goto("https://www.ch.com/flights/",wait_until="domcontentloaded",timeout=30000)
  page.wait_for_timeout(2400)
  log("loaded",dict(url=page.url))
  origin=page.locator('input[name="OriCity"]')
  origin.click()
  origin.fill("成都")
  page.wait_for_timeout(1500)
  log("origin_filled",scan(page))
  date=page.locator('input[name="FDate"]')
  date.click()
  page.wait_for_timeout(900)
  log("date_picker_open",scan(page))
 except Exception as e:
  log("exception",str(e)[:400])
 finally:b.close()
