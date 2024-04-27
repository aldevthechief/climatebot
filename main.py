import os
from git import Repo
from server import keep_alive
from time import sleep

import telebot
import requests
import json
from geopy.geocoders import Nominatim
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

bot_token = os.environ.get('bot_token')
weather_token = os.environ.get('weather_token')

git_username = os.environ.get('git_username')
git_token = os.environ.get('git_token')

bot = telebot.TeleBot(bot_token, threaded=True)

remotelink = f'https://{git_username}:{git_token}@github.com/aldevthechief/climate-bot.git'
gitdir = os.path.join(os.getcwd(), 'data')

try:
    repo = Repo(gitdir)
except:
    repo = Repo.clone_from(remotelink, gitdir, branch='data')

datadir = os.path.join(gitdir, 'geodata.json')
with open(datadir) as file:
    try:
        geodata = json.load(file)
    except json.JSONDecodeError:
        geodata = dict()

weathericons = {'01' : u'\U00002600', 
                '02' : '☁', 
                '03' : '⛅', 
                '04' : '🌫', 
                '09' : u'\U00002614', 
                '10' : u'\U00002614', 
                '11' : u'\U0001F4A8',
                '13' : u'\U00002744'}

# инициализация меню с командами
locationbutton = types.BotCommand('location', 'сменить локацию')
weatherbutton = types.BotCommand('weather', 'показать погоду сейчас')
bot.set_my_commands([weatherbutton, locationbutton])

@bot.message_handler(commands=['start', 'location'])
def get_user_location(message):
    chatid = message.chat.id
    bot.clear_step_handler_by_chat_id(chatid)
    
    if message.text == '/start': 
        bot.send_message(chatid, 'привет')
    curr_message = bot.send_message(chatid, 'напиши название города, в котором хочешь посмотреть погоду')
    bot.register_next_step_handler(curr_message, send_weather)
    return


@bot.message_handler(commands=['weather'])
def weather(message):
    chatid = message.chat.id
    bot.clear_step_handler_by_chat_id(chatid)
    
    global geodata
    if geodata.get(str(chatid)) is None:
        curr_message = bot.send_message(chatid, 'напиши название города, в котором хочешь посмотреть погоду')
        bot.register_next_step_handler(curr_message, send_weather)
    else: 
        send_weather(message, False)
    return
    
    
def send_weather(message, getlocation = True):
    def updategit():
        repo.index.add('geodata.json')
        repo.index.commit('current user data')
        repo.remote().push()
    
    if getlocation and message.text in ['/location', '/weather', '/start']:
        bot.send_message(message.chat.id, 'такого города не существует, попробуй заново', reply_markup=no_location_markup())
        return
    
    replymsg = bot.send_message(message.chat.id, 'секунду, твой запрос обрабатывается...')
    
    global geodata
    if getlocation:
        lat, long = locate_city(message)
        geodata[str(message.chat.id)] = (lat, long)
        
    weatherdata = get_weather(geodata[str(message.chat.id)][0], geodata[str(message.chat.id)][1])
    
    with open(os.path.join(gitdir, 'info.txt'), 'w') as file:
        file.write(json.dumps(weatherdata))
        
    with open(datadir, 'w') as file:
        json.dump(geodata, file)
        
    updategit()
        
    iconstr = weatherdata['list'][0]['weather'][0]['icon'][:-1]
    description = 'сейчас ' + weatherdata['list'][0]['weather'][0]['description'] + ' ' + weathericons.get(iconstr, ' ') + '\n'
    temperature = '\n' + 'на улице ' + str(weatherdata['list'][0]['main']['temp']) + '°C,'
    feelslike = '\n' + 'ощущается как ' + str(weatherdata['list'][0]['main']['feels_like']) + '°C' + '\n'
    humidity = '\n' + 'влажность ' + str(weatherdata['list'][0]['main']['humidity']) + '%'
    wind = '\n' + 'ветер ' + str(round(weatherdata['list'][0]['wind']['speed'])) + ' м/с'
    
    bot.send_message(message.chat.id, description +  temperature +  feelslike + humidity + wind, parse_mode='Markdown', reply_markup=base_keyboard_markup())
    bot.delete_message(message.chat.id, replymsg.message_id)
    
    
def locate_city(message):
    place = message.text
    geocoder = Nominatim(user_agent='my_app')
    
    try:
        locdata = geocoder.geocode(place)
        latitude, longitude = round(locdata.latitude, 5), round(locdata.longitude, 5)
        return latitude, longitude
    except AttributeError:
        bot.send_message(message.chat.id, 'город не найден, попробуй заново', reply_markup=no_location_markup())
        return
   
        
def get_weather(latitude, longitude):
    api = 'https://api.openweathermap.org/data/2.5/forecast?lat={}&lon={}&appid={}'.format(latitude, longitude, weather_token)
    response = requests.get(api, params={'units': 'metric', 'lang': 'ru'})
    return response.json()


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    msg = call.message
    if call.data == 'new_weather':
        bot.edit_message_reply_markup(msg.chat.id, msg.message_id, '')
        weather(msg)
    elif call.data == 'new_location':
        bot.edit_message_reply_markup(msg.chat.id, msg.message_id, '')
        get_user_location(call.message)
        
        
def base_keyboard_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('погода сейчас', callback_data='new_weather'), 
               InlineKeyboardButton('сменить локацию', callback_data='new_location'))
    return markup


def no_location_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('сменить локацию', callback_data='new_location'))
    return markup
     
keep_alive()

while True:
    try:
        bot.infinity_polling()
    except Exception as _ex:
        print(_ex)
        sleep(15)
