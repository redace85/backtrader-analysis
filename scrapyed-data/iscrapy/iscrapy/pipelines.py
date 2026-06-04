# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html


# useful for handling different item types with a single interface
# from itemadapter import ItemAdpter
from scrapy.exceptions import DropItem
import sqlite3
import os
import time


import telebot
from telebot import formatting
from itemadapter import ItemAdapter


class TelegramPipeline:
    '''
    this pipline is used for send telegram msg.
    '''
    def __init__(self, tele_token, alarm_id):
        self.tele_token = tele_token
        self.alarm_id = alarm_id
        self.bot = telebot.TeleBot(self.tele_token, threaded=False)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
                tele_token=crawler.settings.get('TELE_TOKEN'),
                alarm_id=crawler.settings.get('TELE_ALARM_ID'),
                )

    def process_item(self, item, spider):
        ia = ItemAdapter(item)
        msg = ia['msg']
        if msg == '':
            raise DropItem(f'Drop tele item')

        msg = formatting.format_text(msg, separator="\n\n")

        # send message to telegram
        if ia['failed'] is False:
            self.bot.send_message(spider.chat_id, msg, parse_mode='HTML')
        else:
            self.bot.send_message(self.alarm_id, msg, parse_mode='HTML')

        # sleep 1s after sent
        time.sleep(1)

        return item


class StorePipeline:
    '''
    this pipline is used for save data.
    '''
    def __init__(self, db_path):
        self.db_path = db_path
        self._con = None
        self._data = None

    @classmethod
    def from_crawler(cls, crawler):
        obj = cls(db_path=crawler.settings.get('DB_PATH'))
        obj._crawler = crawler
        return obj

    def open_spider(self, spider):
        if spider.name in ("yahoo-finance", "sina-finance"):
            db_name = os.path.join(self.db_path, f'{spider.symbol}.db')
            self._con = sqlite3.connect(db_name)
            self._con.execute(
                'CREATE TABLE IF NOT EXISTS ohlc('
                'timestamp INTEGER PRIMARY KEY, open REAL, high REAL, '
                'low REAL, close REAL, volume INTEGER)'
            )
            self._data = []

    def close_spider(self, spider):
        if spider.name in ("yahoo-finance", "sina-finance") and self._con:
            if self._data:
                cur = self._con.cursor()
                cur.executemany('INSERT OR REPLACE INTO ohlc VALUES(?, ?, ?, ?, ?, ?)', self._data)
                self._con.commit()
            self._con.close()

    def process_item(self, item, spider):
        ia = ItemAdapter(item)
        if ia['failed']:
            return item

        data = ia['data']
        self._data.append((
            data['timestamp'],
            data['open'],
            data['high'],
            data['low'],
            data['close'],
            data['volume']
        ))
        return item

