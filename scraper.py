from auctionscraper import scraper
import logging
import json

logging.basicConfig(level=logging.DEBUG)

# i fuck it
# https://stackoverflow.com/questions/434287/how-to-iterate-over-a-list-in-chunks
def chunker(seq, size):
    return (seq[pos:pos + size] for pos in range(0, len(seq), size))

def scrape(category:str, output:str, day_offset:int=0, days_out:int=365, search_direction:bool=False, batch_size:int=20):
    # LEVEL 1 - scrape schedules from calendars
    calendar_url_list = scraper.get_calendar_list(category, days=day_offset, days_out=days_out, forward=search_direction)
    box_url_list = scraper.get_box_list(calendar_url_list)

    # batch/chunk so it doesn't crash on big inputs
    box_chunks = [chunk for chunk in chunker(box_url_list, batch_size)]

    errors = []
    # do in batches to hedge against fuck shit
    for i in range(len(box_chunks)) :
        # LEVEL 2 - scrape the real data
        data, error = scraper.get_data(box_chunks[i])
        errors.append(error)
        output_i = output + str(i) + ".json"
        # save data
        with open(output_i, 'w') as fout:
            json.dump(data, fout)
            logging.info(f"{category} data batch {i} saved to {output_i}")
    
    error_output_name = output + "_errors.json"
    print("These dates had errors:")
    print(errors)
    errors = sum(errors, [])
    with open(error_output_name, "w") as f :
        json.dump(errors, f)
        logging.info(f"Saved errors to {error_output_name}")
    

if __name__ == '__main__':
    scrape('foreclose', 'history/foreclose', 0, 365*5, False, 25)
    scrape('taxdeed', 'history/taxdeed', 0, 365*5, False, 25)