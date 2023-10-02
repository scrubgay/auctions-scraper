from playwright.sync_api import sync_playwright
from playwright.sync_api import Page
from datetime import date, timedelta
import logging
import re
import time # rate-limiting functions

# Logger
logging.basicConfig(level=logging.DEBUG)

def read_txt(txt:str):
    """ Read subdomain (county) from txt file """
    with open(txt, 'r') as f:
        return [line.strip() for line in f.readlines()]

def create_baseurl(subdomain:str, category:str) -> str:
    """ Create calendar URL """
    if category not in ['foreclose', 'taxdeed']:
        return('Please define "foreclose" or "taxdeed" in category argument')
    else:
        return f"https://{subdomain}.real{category}.com/index.cfm?zaction=USER&zmethod=CALENDAR"

def create_calendar_url(baseurl:str, days:int=0, days_out:int = 90, forward:bool = False) -> list:
    # days_out passed as parameter
    # forward controls whether we search backwards from 'days' offset 
    # or forwards (future auctions)
    """ Get calendar pages to be scraped """
    tday = date.today() + timedelta(days=days)
    calendar = []
    indices = []
    for day in range(0, days_out, 28):
        if forward :
            calendar_date = tday + timedelta(days=day)
        else :
            calendar_date = tday - timedelta(days=day)
        calendar_date = calendar_date.replace(day = 1) # you only need the first day of the month
        index = calendar_date.strftime('%m/%d/%Y')
        if index not in indices:
            indices.append(index)
            date_url = calendar_date.strftime('%m/%d/%Y')
            calendar.append(baseurl + "&selCalDate=" + date_url)
    return calendar

def get_calendar_list(category:str, days:int, days_out:int) -> list:
  """ Get calendar url list to be scraped """
  calendar_url = []
  for subdomain in read_txt(f"{category}.txt"):
      baseurl = create_baseurl(subdomain, category)
      calendar_url += create_calendar_url(baseurl, days=days, days_out=days_out)
  return calendar_url

def parse_box(page:Page) -> list:
    """ Parse url from box calendar """
    calendar_box = page.query_selector_all('div[class*=CALSEL]') # could be CALSEF, CALSET, CALSELB
    box_url = []
    for box in calendar_box:
        day_id = box.get_attribute('dayid')
        if 'foreclose' in re.findall(r'(?<=real)\w+(?=\.com)', page.url):
            category = r'Foreclosure'
        elif 'taxdeed' in re.findall(r'(?<=real)\w+(?=\.com)', page.url):
            category = r'Tax Deed'
        else:
            logging.warning(f"Something wrong when parsing category at ({day_id}): {page.url}")
            continue
        if re.findall(category, box.query_selector('.CALTEXT').inner_text()):
            if int(box.query_selector('.CALACT').inner_text()) > 0:
                url = page.url.split('?')[0] + f"?zaction=AUCTION&Zmethod=PREVIEW&AUCTIONDATE={day_id}"
                box_url.append(url)
    return box_url

def get_box_list(urls:list) -> list:
    """ Get box url from calendar page """
    data = []
    with sync_playwright() as p:
        # open browser
        browser = p.firefox.launch()
        page = browser.new_page()
        page.set_default_timeout(90000)
        for url in urls:
            time.sleep(1) # rate limiting
            # access page
            logging.debug(f"GET {url} | LEVEL 1")
            try:
                page.goto(url)
                page.wait_for_selector('.CALDAYBOX')
                # parse content
                data += parse_box(page)
            except Exception as e:
                logging.warning(f"Failed to GET {url}: {e}")
                continue
        # close browser
        browser.close()
    return data

def get_data(urls:list):
    """ Get auction data """
    data = []
    # open browser
    with sync_playwright() as p:
        browser = p.firefox.launch()
        page = browser.new_page()
        page.set_default_timeout(90000)
        for url in urls:
            time.sleep(1) # rate-limiting, should be parameterized
            # access page
            try:
                page.goto(url)
                page.wait_for_selector('#Area_C > .AUCTION_ITEM.PREVIEW') # change from #Area_W
                cards = page.query_selector_all('#Area_C > .AUCTION_ITEM.PREVIEW')
                # counter
                max_paginate = int(page.query_selector("#maxCA").inner_text())
                auction_date = re.sub(r'^.+AUCTIONDATE=(\d{2}/\d{2}/\d{4})$', '\\1', url)
                for i in range(max_paginate) :
                    logging.debug(f"Page {i + 1} of {max_paginate}")
                    for card in cards:
                        # parse date
                        auction_date = re.sub(r'^.+AUCTIONDATE=(\d{2}/\d{2}/\d{4})$', '\\1', url)
                        # parse fields
                        auction_field = []
                        ## this is for AUCTION_STATS
                        auction_status = card.query_selector(".ASTAT_MSGA").inner_text()
                        if auction_status == "Auction Sold" :
                            auction_status = "Sold"
                            auction_sold_date = card.query_selector(".ASTAT_MSGB").inner_text()
                            auction_amount = card.query_selector(".ASTAT_MSGD").inner_text().replace("$", "").replace(",", "")
                            auction_soldto = card.query_selector(".ASTAT_MSG_SOLDTO_MSG").inner_text()
                        else :
                            auction_status = card.query_selector(".ASTAT_MSGB").inner_text()
                            auction_sold_date = ""
                            auction_amount = ""
                            auction_soldto = ""

                        ## this is for AUCTION_DETAILS
                        for text in card.query_selector_all('tr > th'):
                            th = text.inner_text().replace('#','').replace(':','').strip()
                            if th == '':
                                th = 'city'
                            th = th.lower().replace(' ','_')
                            auction_field.append(th)
                        # parse content
                        auction_content = [text.inner_text().strip() for text in card.query_selector_all('tr > td')]
                        if len(auction_field) == len(auction_content):
                            auction_info = {auction_field[i]:auction_content[i] for i in range(len(auction_field))}
                            fields = list(auction_info.keys())
                            for key in fields:
                                if key == "city":
                                    city = auction_info[key].split(', ')[0].strip()
                                    zipcode = auction_info[key].split(',')[1].strip()
                                    try:
                                        state = zipcode.split('-')[0].strip()
                                        zipcode = zipcode.split('-')[1].strip()
                                    except:
                                        state = 'FL'
                                        zipcode = zipcode
                                    auction_info.update({
                                        'city':city,
                                        'state':state,
                                        'zipcode':zipcode,
                                        'auction_datetime': auction_date,
                                        "auction_status": auction_status,
                                        "auction_sold_date": auction_sold_date,
                                        "auction_soldto": auction_soldto
                                    })
                        else:
                            logging.warning(f"Length of information's fields and contents doesn't matches: {url}")
                            continue
                        data.append(auction_info)
                    if i + 1 < max_paginate :
                        paginate = page.query_selector("#curPCA")
                        paginate.fill(str(i+1))
                        paginate.press("Enter")
                        time.sleep(1)
            except Exception as e:
                logging.warning(f"Failed to GET {url}: {e}")
                error_dates.append(auction_date)
                continue
        # close browser
        browser.close()
    return data, error_dates

if __name__ == '__main__':
    pass
