#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Simple Bot thah look inside the database and see if the pokemon requested is appeared during the last scan
# This program is dedicated to the public domain under the CC0 license.
# First iteration made by eugenio412
# based on timerbot made inside python-telegram-bot example folder

# better on python3.4

'''please READ FIRST the README.md'''


import sys
if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3.")

from telegram.ext import Updater, CommandHandler, Job, MessageHandler, Filters
from telegram import Bot
import logging
from datetime import datetime, timezone
import os
import errno
import json
import threading
import fnmatch
import DataSources
import Preferences
from geopy.geocoders import Nominatim

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)
prefs = Preferences.UserPreferences()
jobs = dict()
geolocator = Nominatim()

# User dependant - dont add
sent = dict()
locks = dict()

# User dependant - Add to clear, addJob, loadUserConfig, saveUserConfig
#search_ids = dict()
#language = dict()
#location_ids = dict()
location_radius = 0.6

#pokemon:
pokemon_name = dict()
#move:
move_name = dict()

#pokemon rarity
pokemon_rarity = [[],
	["13","16","19","41","133"],
	["1","7","10","17","21","23","25","29","32","35","43","46","48","58","60","69","84","92","96","98","120","127","129","147"],
	["2","4","8","11","14","15","18","20","22","27","37","39","42","47","49","50","52","54","56","61","63","66","70","72","74",\
    "77","79","81","86","90","93","95","97","100","102","104","107","108","109","111","114","116","118","123","124","125","126","128","138","140","143"],
	["3","5","6","9","12","24","30","31","33","34","36","44","53","55","57","59","64","67","73","75","78","80","85","88","99",\
    "103","105","106","110","112","113","117","119","121","122","131","134","135","137","142","148","149"],
	["26","28","38","40","45","51","62","65","68","71","76","82","83","87","89","91","94","101","115","130","132","136","139","141","144","145","146","150","151"],
];

rarity_value = ["very common","common","uncommon","rare","very rare","ultrarare"]

# Define a few command handlers. These usually take the two arguments bot and
# update. Error handlers also receive the raised TelegramError object in error.
def cmd_help(bot, update):
    chat_id = update.message.chat_id
    logger.info('[%s] Sending help text.' % (chat_id))
    text = "/help /start \n" + \
    "/add <#pokedexID> \n" + \
    "/add <#pokedexID1> <#pokedexID2> ... \n" + \
    "/addbyrarity <#rarity> - With 1 uncommon to 5 ultrarare \n" + \
    "/clear \n" + \
    "/rem <#pokedexID> \n" + \
    "/rem <#pokedexID1> <#pokedexID2> ... \n" + \
    "Send <location> - Search a location \n" +\
    "/location <s> - Send a location as text \n" +\
    "/radius <m> - Search radius in m \n" +\
    "/remloc - Clear location data\n" +\
    "/list \n" + \
    "/save \n" + \
    "/load \n" + \
    "/lang en"
    bot.sendMessage(chat_id, text)
    tmp = ''
    for key in pokemon_name:
        tmp += "%s, " % (key)
    tmp = tmp[:-2]
    bot.sendMessage(chat_id, text= '/lang [%s]' % (tmp))

def cmd_start(bot, update):
    chat_id = update.message.chat_id
    logger.info('[%s] Starting.' % (chat_id))
    bot.sendMessage(chat_id, text='Hello!')
    cmd_help(bot, update)

def cmd_add(bot, update, args, job_queue):

    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    if len(args) <= 0:
        bot.sendMessage(chat_id, text='usage: "/add <#pokemon>"" or "/add <#pokemon1> <#pokemon2>"')
        return
    addJob(bot, update, job_queue)
    logger.info('[%s] Add pokemon.' % (chat_id))

    try:
        search = pref.get('search_ids')
        for x in args:
            if int(x) not in search:
                search.append(int(x))
        search.sort()
        pref.set('search_ids',search)
        cmd_list(bot, update)
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
        bot.sendMessage(chat_id, text='usage: "/add <#pokemon>"" or "/add <#pokemon1> <#pokemon2>"')

def cmd_addByRarity(bot, update, args, job_queue):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    if len(args) <= 0:
        bot.sendMessage(chat_id, text='usage: "/addbyrarity <#rarity>" with 1 uncommon to 5 ultrarare')
        return

    addJob(bot, update, job_queue)
    logger.info('[%s] Add pokemon by rarity.' % (chat_id))

    try:
        rarity = int(args[0])

        search = pref.get('search_ids')
        for x in pokemon_rarity[rarity]:
            if int(x) not in search:
                search.append(int(x))
        search.sort()
        pref.set('search_ids', search)
        cmd_list(bot, update)
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
        bot.sendMessage(chat_id, text='usage: "/addbyrarity <#rarity>" with 1 uncommon to 5 ultrarare')

def cmd_clear(bot, update):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    """Removes the job if the user changed their mind"""
    logger.info('[%s] Clear list.' % (chat_id))

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return

    # Remove from jobs
    job = jobs[chat_id]
    job.schedule_removal()
    del jobs[chat_id]

    # Remove from sent
    del sent[chat_id]
    # Remove from locks
    del locks[chat_id]

    pref.reset_user()

    bot.sendMessage(chat_id, text='Notifications successfully removed!')

def cmd_remove(bot, update, args, job_queue):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    logger.info('[%s] Remove pokemon.' % (chat_id))

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return

    try:
        search = pref.get('search_ids')
        for x in args:
            if int(x) in search:
                search.remove(int(x))
        pref.set('search_ids',search)
        cmd_list(bot, update)
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
        bot.sendMessage(chat_id, text='usage: /rem <#pokemon>')

def cmd_list(bot, update):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    logger.info('[%s] List.' % (chat_id))

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return

    try:
        lan = pref.get('language')
        tmp = 'List of notifications:\n'
        for x in pref.get('search_ids'):
            tmp += "%i %s\n" % (x, pokemon_name[lan][str(x)])
        bot.sendMessage(chat_id, text = tmp)
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))

def cmd_save(bot, update):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    logger.info('[%s] Save.' % (chat_id))

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return
    pref.set_preferences()
    bot.sendMessage(chat_id, text='Save successful.')

def cmd_load(bot, update, job_queue):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    logger.info('[%s] Attempting to load.' % (chat_id))
    r = pref.load()
    if r is None:
        bot.sendMessage(chat_id, text='You do not have saved preferences.')
        return

    if not r:
        bot.sendMessage(chat_id, text='Already upto date.')
        return
    else:
        bot.sendMessage(chat_id, text='Load successful.')

    # We might be the first user and above failed....
    if len(pref.get('search_ids')) > 0:
        addJob(bot, update, job_queue)
        cmd_list(bot, update)
    else:
        if chat_id not in jobs:
            job = jobs[chat_id]
            job.schedule_removal()
            del jobs[chat_id]

def cmd_lang(bot, update, args):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    try:
        lan = args[0]
        logger.info('[%s] Setting lang.' % (chat_id))

        if lan in pokemon_name:
            pref.set('language',args[0])
            bot.sendMessage(chat_id, text='Language set to [%s].' % (lan))
        else:
            tmp = ''
            for key in pokemon_name:
                tmp += "%s, " % (key)
            tmp = tmp[:-2]
            bot.sendMessage(chat_id, text='This language isn\'t available. [%s]' % (tmp))
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
        bot.sendMessage(chat_id, text='usage: /lang <#language>')

def cmd_location(bot, update):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return

    user_location = update.message.location

    # We set the location from the users sent location.
    pref.set('location', [user_location.latitude, user_location.longitude, location_radius])

    logger.info('[%s] Setting scan location to Lat %s, Lon %s, R %s' % (chat_id,
        pref['location'][0], pref['location'][1], pref['location'][2]))

    # Send confirmation nessage
    bot.sendMessage(chat_id, text="Setting scan location to: %f / %f with radius %.2f m" %
        (pref['location'][0], pref['location'][1], 1000*pref['location'][2]))

def cmd_location_str(bot, update,args):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return

    if len(args) <= 0:
        bot.sendMessage(chat_id, text='You have not supplied a location')
        return

    try:
        user_location = geolocator.geocode(' '.join(args))
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
        bot.sendMessage(chat_id, text='Location not found, or openstreetmap is down.')
        return

    # We set the location from the users sent location.
    pref.set('location', [user_location.latitude, user_location.longitude, location_radius])

    logger.info('[%s] Setting scan location to Lat %s, Lon %s, R %s' % (chat_id,
        pref['location'][0], pref.preferences['location'][1], pref.preferences['location'][2]))

    # Send confirmation nessage
    bot.sendMessage(chat_id, text="Setting scan location to: %f / %f with radius %.2f m" %
        (pref['location'][0], pref['location'][1], 1000*pref['location'][2]))


def cmd_radius(bot, update, args):

    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)

    if chat_id not in jobs:
        bot.sendMessage(chat_id, text='You have no active scanner.')
        return

    # Check if user has set a location
    user_location = pref.get('location')

    if user_location[0] is None:
        bot.sendMessage(chat_id, text="You have not sent a location. Do that first!")
        return

    # Get the users location
    logger.info('[%s] Retrieved Location as Lat %s, Lon %s, R %s (Km)' % (
    chat_id, user_location[0], user_location[1], user_location[2]))

    if len(args) < 1:
        bot.sendMessage(chat_id, text="Current scan location is: %f / %f with radius %.2f m"
                                      % (user_location[0], user_location[1], user_location[2]))
        return

    # Change the radius
    pref.set('location', [user_location[0], user_location[1], float(args[0])/1000])

    logger.info('[%s] Set Location as Lat %s, Lon %s, R %s (Km)' % (chat_id, pref['location'][0],
        pref['location'][1], pref['location'][2]))

    # Send confirmation
    bot.sendMessage(chat_id, text="Setting scan location to: %f / %f with radius %.2f m" % (pref['location'][0],
        pref['location'][1], 1000*pref['location'][2]))

def cmd_clearlocation(bot, update):
    chat_id = update.message.chat_id
    pref = prefs.get(chat_id)
    pref.set('location', [None, None, None])
    bot.sendMessage(chat_id, text='Your location has been removed.')
    logger.info('[%s] Location has been unset' % chat_id)

## Functions
def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))

def alarm(bot, job):
    chat_id = job.context[0]
    logger.info('[%s] Checking alarm.' % (chat_id))
    checkAndSend(bot, chat_id, prefs.get(chat_id).get('search_ids'))

def addJob(bot, update, job_queue):
    chat_id = update.message.chat_id
    logger.info('[%s] Adding job.' % (chat_id))

    try:
        if chat_id not in jobs:
            job = Job(alarm, 30, repeat=True, context=(chat_id, "Other"))
            # Add to jobs
            jobs[chat_id] = job
            job_queue.put(job)

            # User dependant
            if chat_id not in sent:
                sent[chat_id] = dict()
            if chat_id not in locks:
                locks[chat_id] = threading.Lock()
            text = "Scanner started."
            bot.sendMessage(chat_id, text)
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))

def checkAndSend(bot, chat_id, pokemons):
    pref = prefs.get(chat_id)
    lock = locks[chat_id]
    logger.info('[%s] Checking pokemon and sending notifications.' % (chat_id))
    if len(pokemons) == 0:
        return

    try:
        allpokes = dataSource.getPokemonByIds(pokemons)
        lan = pref['language']
        mySent = sent[chat_id]
        location_data = pref['location']

        sendPokeWithoutIV = config.get('SEND_POKEMON_WITHOUT_IV', True)
        pokeMinIVFilterList = config.get('POKEMON_MIN_IV_FILTER_LIST', dict())

        moveNames = move_name["en"]
        if lan in move_name:
            moveNames = move_name[lan]

        lock.acquire()

        for pokemon in allpokes:
            if location_data[0] is not None:
                if not pokemon.filterbylocation(location_data):
                    continue

            encounter_id = pokemon.getEncounterID()
            spaw_point = pokemon.getSpawnpointID()
            pok_id = pokemon.getPokemonID()
            latitude = pokemon.getLatitude()
            longitude = pokemon.getLongitude()
            disappear_time = pokemon.getDisappearTime()
            iv = pokemon.getIVs()
            move1 = pokemon.getMove1()
            move2 = pokemon.getMove2()

            delta = disappear_time - datetime.utcnow()
            delta = '%02d:%02d' % (int(delta.seconds / 60), int(delta.seconds % 60))
            disappear_time_str = disappear_time.replace(tzinfo=timezone.utc).astimezone(tz=None).strftime("%H:%M:%S")

            title =  pokemon_name[lan][pok_id]
            address = "Disappear at %s (%s)." % (disappear_time_str, delta)

            if iv is not None:
                title += " IV:%s" % (iv)

            if move1 is not None and move2 is not None:
                # Use language if other move languages are available.
                move1Name = moveNames[move1]
                move2Name = moveNames[move2]
                address += " Moves: %s,%s" % (move1Name, move2Name)

            pokeMinIV = None
            if pok_id in pokeMinIVFilterList:
                pokeMinIV = pokeMinIVFilterList[pok_id]

            if encounter_id not in mySent:
                mySent[encounter_id] = disappear_time

                ivNoneAndSendWithout = (iv is None) and sendPokeWithoutIV
                ivNotNoneAndPokeMinIVNone = (iv is not None) and (pokeMinIV is None)
                ivHigherEqualFilter = (iv is not None) and (pokeMinIV is not None) and (float(iv) >= float(pokeMinIV))
                if (not ivAvailable or ivNoneAndSendWithout or ivNotNoneAndPokeMinIVNone or ivHigherEqualFilter):
                    if not config.get('SEND_MAP_ONLY', True):
                        real_loc = geolocator.reverse(", ".join([pokemon.getLatitude(), pokemon.getLongitude()]))
                        bot.sendMessage(chat_id, text = '%s - %s\n%s' % (title, address,real_loc.address))
                    bot.sendVenue(chat_id, latitude, longitude, title, address)

    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
    lock.release()

    # Clean already disappeared pokemon
    # 2016-08-19 20:10:10.000000
    # 2016-08-19 20:10:10
    try:
        current_time = datetime.utcnow()
        lock.acquire()
        toDel = []
        for encounter_id in mySent:
            time = mySent[encounter_id]
            if time < current_time:
                toDel.append(encounter_id)
        for encounter_id in toDel:
            del mySent[encounter_id]
    except Exception as e:
        logger.error('[%s] %s' % (chat_id, repr(e)))
    lock.release()

def read_config():
    config_path = os.path.join(
        os.path.dirname(sys.argv[0]), "config-bot.json")
    logger.info('Reading config: <%s>' % config_path)
    global config

    try:
        with open(config_path, "r", encoding='utf-8') as f:
            config = json.loads(f.read())
    except Exception as e:
        logger.error('%s' % (repr(e)))
        config = {}
    report_config()

def report_config():
    logger.info('TELEGRAM_TOKEN: <%s>' % (config.get('TELEGRAM_TOKEN', None)))
    logger.info('SCANNER_NAME: <%s>' % (config.get('SCANNER_NAME', None)))
    logger.info('DB_TYPE: <%s>' % (config.get('DB_TYPE', None)))
    logger.info('DB_CONNECT: <%s>' % (config.get('DB_CONNECT', None)))
    logger.info('DEFAULT_LANG: <%s>' % (config.get('DEFAULT_LANG', None)))
    logger.info('SEND_MAP_ONLY: <%s>' % (config.get('SEND_MAP_ONLY', None)))
    logger.info('SEND_POKEMON_WITHOUT_IV: <%s>' % (config.get('SEND_POKEMON_WITHOUT_IV', None)))
    poke_ivfilter_list = config.get('POKEMON_MIN_IV_FILTER_LIST', dict())
    tmp = ''
    for poke_id in poke_ivfilter_list:
        tmp = '%s %s:%s' % (tmp, poke_id, poke_ivfilter_list[poke_id])
    tmp = tmp[1:]
    logger.info('POKEMON_MIN_IV_FILTER_LIST: <%s>' % (tmp))

def read_pokemon_names(loc):
    logger.info('Reading pokemon names. <%s>' % loc)
    config_path = "locales/pokemon." + loc + ".json"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            pokemon_name[loc] = json.loads(f.read())
    except Exception as e:
        logger.error('%s' % (repr(e)))
        # Pass to ignore if some files missing.
        pass

def read_move_names(loc):
    logger.info('Reading move names. <%s>' % loc)
    config_path = "locales/moves." + loc + ".json"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            move_name[loc] = json.loads(f.read())
    except Exception as e:
        logger.error('%s' % (repr(e)))
        # Pass to ignore if some files missing.
        pass

def getUserConfigPath(chat_id):
    logger.info('[%s] getUserConfigPath.' % (chat_id))
    user_path = os.path.join(
        os.path.dirname(sys.argv[0]), "userdata")
    try:
        os.makedirs(user_path)
    except OSError as e:
        if e.errno != errno.EEXIST:
            logger.error('[%s] %s' % (chat_id, e))
    return os.path.join(user_path, '%s.json' % chat_id)

def main():
    logger.info('Starting...')
    read_config()

    # Read lang files
    path_to_local = "locales/"
    for file in os.listdir(path_to_local):
        if fnmatch.fnmatch(file, 'pokemon.*.json'):
            read_pokemon_names(file.split('.')[1])
        if fnmatch.fnmatch(file, 'moves.*.json'):
            read_move_names(file.split('.')[1])

    dbType = config.get('DB_TYPE', None)
    scannerName = config.get('SCANNER_NAME', None)
    global dataSource
    dataSource = None
    global ivAvailable
    ivAvailable = False
    if dbType == 'sqlite':
        if scannerName == 'pogom':
            dataSource = DataSources.DSPogom(config.get('DB_CONNECT', None))
        elif scannerName == 'pokemongo-map':
            dataSource = DataSources.DSPokemonGoMap(config.get('DB_CONNECT', None))
        elif scannerName == 'pokemongo-map-iv':
            dataSource = DataSources.DSPokemonGoMapIV(config.get('DB_CONNECT', None))
            ivAvailable = True
    elif dbType == 'mysql':
        if scannerName == 'pogom':
            dataSource = DataSources.DSPogomMysql(config.get('DB_CONNECT', None))
        elif scannerName == 'pokemongo-map':
            dataSource = DataSources.DSPokemonGoMapMysql(config.get('DB_CONNECT', None))
        elif scannerName == 'pokemongo-map-iv':
            dataSource = DataSources.DSPokemonGoMapIVMysql(config.get('DB_CONNECT', None))
            ivAvailable = True
    if not dataSource:
        raise Exception("The combination SCANNER_NAME, DB_TYPE is not available: %s,%s" % (scannerName, dbType))

    #ask it to the bot father in telegram
    token = config.get('TELEGRAM_TOKEN', None)
    updater = Updater(token)
    b = Bot(token)
    logger.info("BotName: <%s>" % (b.name))

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(CommandHandler("help", cmd_help))
    dp.add_handler(CommandHandler("add", cmd_add, pass_args = True, pass_job_queue=True))
    dp.add_handler(CommandHandler("addbyrarity", cmd_addByRarity, pass_args = True, pass_job_queue=True))
    dp.add_handler(CommandHandler("clear", cmd_clear))
    dp.add_handler(CommandHandler("rem", cmd_remove, pass_args = True, pass_job_queue=True))
    dp.add_handler(CommandHandler("save", cmd_save))
    dp.add_handler(CommandHandler("load", cmd_load, pass_job_queue=True))
    dp.add_handler(CommandHandler("list", cmd_list))
    dp.add_handler(CommandHandler("lang", cmd_lang, pass_args = True))
    dp.add_handler(CommandHandler("radius", cmd_radius, pass_args=True))
    dp.add_handler(CommandHandler("location", cmd_location_str, pass_args=True))
    dp.add_handler(CommandHandler("remloc", cmd_clearlocation))
    dp.add_handler(MessageHandler([Filters.location],cmd_location))

    # log all errors
    dp.add_error_handler(error)

    # add the configuration to the preferences
    prefs.add_config(config)

    # Start the Bot
    updater.start_polling()

    logger.info('Started!')
    # Block until the you presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

if __name__ == '__main__':
    main()
