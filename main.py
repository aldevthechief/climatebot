import os
from git import Repo
from server import keep_alive
from time import sleep

import telebot
import requests
import json
from geopy.geocoders import Nominatim
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton
from threading import Thread

from scheduler import Scheduler
import datetime as dt
from datetime import timedelta, date
import pytz
from timezonefinder import TimezoneFinder

run_thread = True
sch = Scheduler(tzinfo=dt.timezone.utc)

def run_schedule():
    while run_thread: 
        sch.exec_jobs()
        sleep(1)


def run_bot():
    bot_token = os.environ.get('bot_token')
    weather_token = os.environ.get('weather_token')
    
    git_username = os.environ.get('git_username')
    git_token = os.environ.get('git_token')
        
    bot = telebot.TeleBot(bot_token, threaded=False)

    remotelink = f'https://{git_username}:{git_token}@github.com/aldevthechief/climatebot-data.git'
    gitdir = os.path.join(os.getcwd(), 'data')

    try:
        repo = Repo(gitdir)
    except:
        repo = Repo.clone_from(remotelink, gitdir, branch='data')

    geodata = dict()
    geodatadir = os.path.join(gitdir, 'geodata.json')
    with open(geodatadir) as file:
        try:
            geodata = json.load(file)
        except json.JSONDecodeError: pass
        
    scheduleinfo = dict()   
    scheduledir = os.path.join(gitdir, 'scheduleinfo.json')
    with open(scheduledir) as file:
        try:
            scheduleinfo = json.load(file)
        except json.JSONDecodeError: pass
        
    weathericons = {'01' : u'\U00002600', 
                    '02' : '☁', 
                    '03' : '⛅', 
                    '04' : '🌫', 
                    '09' : u'\U00002614', 
                    '10' : u'\U00002614', 
                    '11' : u'\U0001F4A8',
                    '13' : u'\U00002744'}

    locationbutton = types.BotCommand('location', 'сменить локацию')
    weatherbutton = types.BotCommand('weather', 'показать погоду сейчас')
    dailyweatherbutton = types.BotCommand('dailyweather', 'показать прогноз погоды на 4 дня')
    bot.set_my_commands([weatherbutton, locationbutton, dailyweatherbutton])
    
    
    def updategit():
        repo.index.add('geodata.json')
        repo.index.add('scheduleinfo.json')
        repo.index.commit('current user data')
        repo.remote().push()


    @bot.message_handler(commands=['start', 'location'])
    def get_user_location(message):
        chatid = message.chat.id
        bot.clear_step_handler_by_chat_id(chatid)
        
        if message.text == '/start': 
            bot.send_message(chatid, 'привет')
        curr_message = bot.send_message(chatid, 'напиши название города, в котором хочешь посмотреть погоду')
        bot.register_next_step_handler(curr_message, send_weather)


    @bot.message_handler(commands=['weather'])
    def weather(message):
        chatid = message.chat.id
        bot.clear_step_handler_by_chat_id(chatid)
        
        if geodata.get(str(chatid)) is None:
            curr_message = bot.send_message(chatid, 'напиши название города, в котором хочешь посмотреть погоду')
            bot.register_next_step_handler(curr_message, send_weather)
        else: 
            send_weather(message, False)


    @bot.message_handler(commands=['dailyweather'])
    def daily_weather(message):
        chatid = message.chat.id
        bot.clear_step_handler_by_chat_id(chatid)
        
        if geodata.get(str(chatid)) is None:
            curr_message = bot.send_message(chatid, 'напиши название города, в котором хочешь посмотреть погоду по дням')
            bot.register_next_step_handler(curr_message, choose_daily_weather)
        else: 
            choose_daily_weather(message, False)


    def set_notification(message):
        chatid = message.chat.id
        bot.clear_step_handler_by_chat_id(chatid)
        
        if scheduleinfo.get(str(chatid)) is None:
            replymarkup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            replymarkup.add(KeyboardButton('отправить местоположение 📍', request_location=True))
            geotext = 'для того чтобы я синхронизировал свое время с твоим, отправь мне свое местоположение'
            geomsg = bot.send_message(chatid, geotext, reply_markup=replymarkup)
            bot.register_next_step_handler(geomsg, get_notification_time)
        else:
            get_notification_time(message, False)


    def get_notification_time(message, gotlocation = True):
        chatid = str(message.chat.id)
        
        timezone = ''
        if gotlocation:
            try:
                timezone = TimezoneFinder().timezone_at(lat=message.location.latitude, lng=message.location.longitude)
            except AttributeError:
                bot.send_message(message.chat.id, 'не удалось распознать твою геолокацию, попробуй заново', reply_markup=locationnotrecognized_markup())
                return
            
            scheduleinfo.pop(chatid, None)
            scheduleinfo[chatid] = [message.location.latitude, message.location.longitude, '']
        else:
            timezone = TimezoneFinder().timezone_at(lat=scheduleinfo[chatid][0], lng=scheduleinfo[chatid][1])
            
        
        askfortime = 'напиши мне время (в 24-х часовом формате), в которое ты хочешь каждый день получать уведомления'
        timemsg = bot.send_message(message.chat.id, askfortime, reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(timemsg, schedule_notification, timezone)
        

    def schedule_notification(message, timezone):
        msgstr = message.text.replace('-', ':').replace(' ', '')
        
        try:
            scheduledtime = dt.datetime.strptime(msgstr, '%H:%M').time()
        except ValueError:
            bot.send_message(message.chat.id, 'не удалось распознать время, попробуй заново', reply_markup=timenotrecognized_markup())
            return
        
        dt_timezone = dt.timezone(dt.datetime.now(pytz.timezone(timezone)).utcoffset())
        
        global run_thread
        run_thread = False
        
        sch.delete_jobs({str(message.chat.id)})
        sch.daily(scheduledtime.replace(tzinfo=dt_timezone), send_weather_notification, args=(message.chat.id,), tags={str(message.chat.id)})
        
        run_thread = True
            
        scheduleinfo[str(message.chat.id)][2] = scheduledtime.strftime('%H:%M')
        
        confirmmsg = f"отлично, теперь тебе ежедневно в { scheduledtime.strftime('%H:%M') } будут приходить уведомления о погоде в выбранной локации"
        bot.send_message(message.chat.id, confirmmsg, reply_markup=base_keyboard_markup())    
        
        with open(scheduledir, 'w') as file:
            json.dump(scheduleinfo, file)
            
        updategit() 
            
        
    def send_weather(message, getlocation = True):
        if getlocation and message.text in ['/location', '/weather', '/start', '/dailyweather']:
            bot.send_message(message.chat.id, 'такого города не существует, попробуй заново', reply_markup=no_location_markup())
            return
        
        replymsg = bot.send_message(message.chat.id, 'секунду, твой запрос обрабатывается...')
        
        if getlocation:
            lat, long = locate_city(message, replymsg)
            geodata[str(message.chat.id)] = (lat, long)
            
        weatherdata = get_weather(geodata[str(message.chat.id)][0], geodata[str(message.chat.id)][1])
            
        with open(geodatadir, 'w') as file:
            json.dump(geodata, file)
            
        updategit()
            
        iconstr = weatherdata['list'][0]['weather'][0]['icon'][:-1]
        description = 'сейчас ' + weatherdata['list'][0]['weather'][0]['description'] + ' ' + weathericons.get(iconstr, ' ') + '\n'
        temperature = '\n' + 'на улице ' + str(weatherdata['list'][0]['main']['temp']) + '°C,'
        feelslike = '\n' + 'ощущается как ' + str(weatherdata['list'][0]['main']['feels_like']) + '°C' + '\n'
        precipiation = '\n' + 'вероятность осадков ' + str(int(weatherdata['list'][0]['pop'] * 100)) + '%'
        wind = '\n' + 'ветер ' + str(round(weatherdata['list'][0]['wind']['speed'])) +' м/с'
        humidity = '\n' + 'влажность ' + str(weatherdata['list'][0]['main']['humidity']) + '%'
        
        showprecipiation = precipiation if weatherdata['list'][0]['pop'] > 0 else ''
        resstring = description +  temperature +  feelslike + wind + showprecipiation + humidity
        
        bot.send_message(message.chat.id, resstring, parse_mode='Markdown', reply_markup=base_keyboard_markup())
        bot.delete_message(message.chat.id, replymsg.message_id)
        
        
    def send_weather_notification(chatid):
        try:
            weatherdata = get_weather(geodata[str(chatid)][0], geodata[str(chatid)][1])
        except KeyError: return
            
        iconstr = weatherdata['list'][0]['weather'][0]['icon'][:-1]
        description = 'сейчас ' + weatherdata['list'][0]['weather'][0]['description'] + ' ' + weathericons.get(iconstr, ' ') + '\n'
        temperature = '\n' + 'на улице ' + str(weatherdata['list'][0]['main']['temp']) + '°C,'
        feelslike = '\n' + 'ощущается как ' + str(weatherdata['list'][0]['main']['feels_like']) + '°C' + '\n'
        precipiation = '\n' + 'вероятность осадков ' + str(int(weatherdata['list'][0]['pop'] * 100)) + '%'
        wind = '\n' + 'ветер ' + str(round(weatherdata['list'][0]['wind']['speed'])) +' м/с'
        humidity = '\n' + 'влажность ' + str(weatherdata['list'][0]['main']['humidity']) + '%'
        
        showprecipiation = precipiation if weatherdata['list'][0]['pop'] > 0 else ''
        resstring = description +  temperature +  feelslike + wind + showprecipiation + humidity
          
        bot.send_message(chatid, resstring, parse_mode='Markdown', reply_markup=base_keyboard_markup())
        
        
    def choose_daily_weather(message, getlocation = True):
        if getlocation:
            if message.text in ['/location', '/weather', '/start', '/dailyweather']:
                bot.send_message(message.chat.id, 'такого города не существует, попробуй заново', reply_markup=no_location_markup())
                return
            lat, long = locate_city(message)
            geodata[str(message.chat.id)] = (lat, long)
        
        availabledays = ['погода на завтра'] + ['погода ' + (date.today() + timedelta(days=shift)).strftime('%d.%m.%Y') for shift in range(2, 5)]
        bot.send_message(message.chat.id, 'выбери тот день, на который ты хочешь посмотреть погоду:', reply_markup=choose_day_markup(availabledays))
        
        
    def send_daily_weather(message, chosenday):
        replymsg = bot.send_message(message.chat.id, 'секунду, твой запрос обрабатывается...')
        
        dailyweatherdata = get_weather(geodata[str(message.chat.id)][0], geodata[str(message.chat.id)][1])
            
        with open(geodatadir, 'w') as file:
            json.dump(geodata, file)
            
        updategit()
            
        dailyweatherinfo = fetch_daily_weather(dailyweatherdata['list'])
        
        day, info = list(dailyweatherinfo.items())[int(chosenday.data)]
        date = '\n' + 'погода на ' + day + ':' + '\n'
        w_type = '\n' + 'будет ' + str(info[0]) + ' ' + weathericons.get(info[1], ' ') + '\n'
        temprange = '\n' + 'от ' + str(info[2][0]) + '°C' + ' до ' + str(info[2][1]) + '°C' + '\n'
        precipiation = 'вероятность осадков ' + str(int(info[5] * 100)) + '%' + '\n'
        wind = 'ветер ' + str(info[4]) + ' м/с'
        
        finalstr = date + w_type + temprange + (precipiation if info[5] > 0 else '') + wind
            
        bot.send_message(message.chat.id, finalstr, parse_mode='Markdown', reply_markup=base_keyboard_markup())
        bot.delete_message(message.chat.id, replymsg.message_id)
        bot.delete_message(message.chat.id, chosenday.message.message_id)
        
        
    def fetch_daily_weather(data):
        resinfo = dict()
        
        for i in range(8, len(data), 8):
            daydata = data[i: i + 8]
            
            weather_types = dict()
            
            mintemp, maxtemp = 100, -100
            maxprecip = 0
            
            avgtemp = 0
            avgwind = 0
            divcount = 0
            
            for hourweather in daydata:
                divcount += 1
                avgtemp += hourweather['main']['feels_like']
                avgwind += hourweather['wind']['speed']
                
                mintemp = min(mintemp, hourweather['main']['temp_min'])
                maxtemp = max(maxtemp, hourweather['main']['temp_max'])
                maxprecip = max(maxprecip, hourweather['pop'])
                
                hourdesc = hourweather['weather'][0]['description']
                houricon = hourweather['weather'][0]['icon'][:-1]
                weather_types[hourdesc] = (weather_types.get(hourdesc, (0, houricon))[0] + 1, houricon)
                
            sortedtypes = dict(sorted(weather_types.items(), key=lambda x: x[1][0], reverse=True))
            mainweather = next(iter(sortedtypes))
            mainicon = sortedtypes[mainweather][1]
            
            dayweather = [mainweather, mainicon, (mintemp, maxtemp), round(avgtemp / divcount, 2), round(avgwind / divcount), maxprecip]
            
            formatteddate = dt.datetime.strptime(daydata[0]['dt_txt'].split()[0], '%Y-%m-%d').strftime('%d.%m.%Y')
            resinfo[formatteddate] = dayweather
            
        return resinfo
            
        
    def locate_city(message, waitmsg = None):
        place = message.text 
        geocoder = Nominatim(user_agent='my_app')
        
        try:
            locdata = geocoder.geocode(place)
            latitude, longitude = round(locdata.latitude, 5), round(locdata.longitude, 5)
            return latitude, longitude
        except AttributeError:
            bot.send_message(message.chat.id, 'город не найден, попробуй заново', reply_markup=no_location_markup())
            if waitmsg is not None:
                bot.delete_message(waitmsg.chat.id, waitmsg.message_id)
    
            
    def get_weather(latitude, longitude):
        api = 'https://api.openweathermap.org/data/2.5/forecast?lat={}&lon={}&appid={}'.format(latitude, longitude, weather_token)
        response = requests.get(api, params={'units': 'metric', 'lang': 'ru'})
        return response.json()


    def clear_notification(msg):
        chatid = msg.chat.id
        
        if str(chatid) not in scheduleinfo: 
            bot.edit_message_text('ты пока что не настроил ни одного уведомления', chatid, msg.message_id, reply_markup=base_keyboard_markup())
            return
        
        global run_thread
        run_thread = False
        
        sch.delete_jobs({str(chatid)})
        scheduleinfo.pop(str(chatid), None)
        bot.edit_message_text('твое уведомление успешно очищено', chatid, msg.message_id, reply_markup=base_keyboard_markup())
        
        run_thread = True
        
        with open(scheduledir, 'w') as file:
            json.dump(scheduleinfo, file)
            
        updategit() 


    @bot.callback_query_handler(func=lambda call: True)
    def callback_query(call):
        msg = call.message
        bot.edit_message_reply_markup(msg.chat.id, msg.message_id, '')
        
        if call.data == 'new_weather': weather(msg)
        elif call.data == 'new_location': get_user_location(msg)
        elif call.data == 'new_daily_weather': daily_weather(msg)
        elif call.data == 'new_setup_notification': 
            schtime = scheduleinfo.get(str(msg.chat.id), '   ')[2]
            choosestring = 'выбери действие с уведомлениями, которое ты хочешь сделать\n' + (f'\nна данный момент у тебя настроено ежедневное уведомление о погоде в {schtime}' if schtime != ' ' else '')
            bot.send_message(msg.chat.id, choosestring, reply_markup=setup_notifs_markup())
        elif call.data == 'new_create_notification': 
            set_notification(msg)
            bot.delete_message(msg.chat.id, msg.message_id)
        elif call.data == 'new_delete_notification': clear_notification(msg)
        elif call.data == 'new_time' : set_notification(msg)
        elif call.data.isdigit(): send_daily_weather(msg, call)
            
            
    def base_keyboard_markup():
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton('погода сейчас', callback_data='new_weather'), 
                InlineKeyboardButton('сменить локацию', callback_data='new_location'),
                InlineKeyboardButton('прогноз погоды на 4 дня', callback_data='new_daily_weather'))
        markup.add(InlineKeyboardButton('настроить уведомление о погоде', callback_data='new_setup_notification'))
        return markup


    def choose_day_markup(daystochoose, buttonstodel = []):
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(*[InlineKeyboardButton(daystochoose[i], callback_data=str(i)) for i in range(len(daystochoose)) if i not in buttonstodel])
        return markup


    def no_location_markup():
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('сменить локацию', callback_data='new_location'))
        return markup


    def timenotrecognized_markup():
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('ввести другое время', callback_data='new_time'))
        return markup
    
    
    def locationnotrecognized_markup():
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton('отправить локацию заново', callback_data='new_create_notification'))
        return markup


    def setup_notifs_markup():
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton('настроить новое уведомление', callback_data='new_create_notification'), 
                   InlineKeyboardButton('очистить старое уведомление', callback_data='new_delete_notification'))
        return markup
    
    
    for key, value in scheduleinfo.items():
        zone = TimezoneFinder().timezone_at(lat=scheduleinfo[key][0], lng=scheduleinfo[key][1])
        dt_timezone = dt.timezone(dt.datetime.now(pytz.timezone(zone)).utcoffset())
        
        scheduletime = dt.datetime.strptime(value[2], '%H:%M').time().replace(tzinfo=dt_timezone)
        sch.daily(scheduletime, send_weather_notification, args=(int(key),), tags={key})
        
    schedule_thread = Thread(target=run_schedule)
    schedule_thread.start()


    while True: 
        keep_alive()
        try:
            bot.infinity_polling()
        except Exception as _ex:
            print(_ex)
            sleep(15)


if __name__ == '__main__':
    bot_thread = Thread(target=run_bot)
    bot_thread.start()
