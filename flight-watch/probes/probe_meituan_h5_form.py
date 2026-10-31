"""Inspect Meituan H5 flight form and test visible date/city UI only."""
import json,re
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright
URL="https://i.meituan.com/awp/hfe/hfe-dianping-flight/index/index.html?h5_source=meituan&h5=1"
def emit(stage,**kw):
 print("MEITUAN_STEP "+json.dumps({"stage":stage,"checked_at_utc":datetime.now(timezone.utc).isoformat(),**kw},ensure_ascii=False),flush=True)
def state(page):
 return page.evaluate("""() => {
  const texts=['北京','上海','搜索','成都','阿勒泰','11月01日'];
  const elements=[...document.querySelectorAll('body *')].filter(e=>e.children.length===0&&texts.includes((e.innerText||'').trim()));
  return {
    url:location.href,title:document.title,
    body:(document.body?.innerText||'').slice(0,1800),
    matching:elements.slice(0,24).map(e=>({text:(e.innerText||'').slice(0,55),html:e.outerHTML.slice(0,400),parent:e.parentElement?.outerHTML.slice(0,800)})),
    inputs:[...document.querySelectorAll('input')].slice(0,20).map(e=>({html:e.outerHTML.slice(0,300)})),
    containers:[...document.querySelectorAll('[class*="flight"],[class*="city"],[class*="date"],[class*="search"]')].filter(e=>e.getBoundingClientRect().width>0).slice(0,22).map(e=>({html:e.outerHTML.slice(0,250)}))
  }
}""")
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 ctx=b.new_context(viewport={"width":390,"height":844},locale="zh-CN",is_mobile=True,has_touch=True)
 page=ctx.new_page()
 try:
  page.goto(URL,wait_until="domcontentloaded",timeout=30000)
  page.wait_for_timeout(3500)
  emit("form",details=state(page))
  try:
   page.get_by_text("北京",exact=True).first.click(timeout=4000)
   page.wait_for_timeout(700)
   emit("origin_picker",details=state(page))
  except Exception as e:emit("origin_click_error",error=str(e)[:220])
  try:
   loc=page.get_by_text("成都",exact=True)
   emit("chengdu_match_count",count=loc.count())
   if loc.count():
    loc.last.click(timeout=3000)
    page.wait_for_timeout(450)
    emit("origin_chengdu",details=state(page))
  except Exception as e:emit("chengdu_click_error",error=str(e)[:220])
  try:
   page.get_by_text("上海",exact=True).first.click(timeout=4000)
   page.wait_for_timeout(500)
   emit("destination_picker",details=state(page))
  except Exception as e:emit("destination_click_error",error=str(e)[:230])
  try:
   inp=page.locator("#search-input")
   inp.fill("阿勒泰")
   page.wait_for_timeout(1300)
   emit("altay_search",details=state(page))
   loc=page.get_by_text("阿勒泰",exact=True)
   emit("altay_match_count",count=loc.count())
   if loc.count():
    loc.last.click(timeout=3000)
    page.wait_for_timeout(550)
    emit("destination_altay",details=state(page))
    page.locator(".select-date").first.click(timeout=3500)
    page.wait_for_timeout(750)
    emit("date_picker",details=state(page))
    months=page.locator(".flight-calendar .dp-date")
    emit("calendar_months",count=months.count(),
         samples=[months.nth(i).inner_text()[:180] for i in range(min(4,months.count()))],
         december_header_count=page.get_by_text("2026年12月",exact=True).count())
    if months.count()>=3:
     dec=months.nth(2)
     candidates=dec.get_by_text("9",exact=True)
     emit("dec_ninth_candidates",count=candidates.count())
     if candidates.count():
      candidates.first.click(timeout=7000)
      page.wait_for_timeout(650)
      emit("selected_date",details=state(page))
      label=page.locator(".select-date").first.inner_text()
      if "12月09日" in label or "12月9日" in label:
       page.locator("button.button").first.click(timeout=5000)
       page.wait_for_timeout(9000)
       emit("searched_real_flights",details=state(page),
            fare_evidence_uncertain=True)
      else:
       emit("date_not_confirmed",label=label)
  except Exception as e:emit("altay_click_error",error=str(e)[:220])
 finally:
  b.close()
