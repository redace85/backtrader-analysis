#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015, 2016, 2017 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################

import collections
from copy import copy
from datetime import date, datetime, timedelta
import threading
import uuid

from backtrader.feed import DataBase
from backtrader import (TimeFrame, num2date, date2num, BrokerBase,
                        Order, OrderBase, OrderData)
from backtrader.utils.py3 import bytes, bstr, with_metaclass, queue, MAXFLOAT
from backtrader.metabase import MetaParams
from backtrader.comminfo import CommInfoBase
from backtrader.position import Position
from backtrader.stores import ibstore
from backtrader.utils import AutoDict, AutoOrderedDict
from backtrader.comminfo import CommInfoBase

from mock_store import Mock_Store

class MetaMockBroker(BrokerBase.__class__):
    def __init__(cls, name, bases, dct):
        '''Class has already been created ... register'''
        # Initialize the class
        super().__init__(name, bases, dct)
        Mock_Store.BrokerCls = cls


class MockBroker(with_metaclass(MetaMockBroker, BrokerBase)):
    '''Broker implementation for Interactive Brokers.

    This class maps the orders/positions from Interactive Brokers to the
    internal API of ``backtrader``.

    Notes:

      - ``tradeid`` is not really supported, because the profit and loss are
        taken directly from IB. Because (as expected) calculates it in FIFO
        manner, the pnl is not accurate for the tradeid.

      - Position

        If there is an open position for an asset at the beginning of
        operaitons or orders given by other means change a position, the trades
        calculated in the ``Strategy`` in cerebro will not reflect the reality.

        To avoid this, this broker would have to do its own position
        management which would also allow tradeid with multiple ids (profit and
        loss would also be calculated locally), but could be considered to be
        defeating the purpose of working with a live broker
    '''
    params = ()

    def __init__(self, **kwargs):
        super().__init__()

        self.mock_store = self.Mock_Store(**kwargs)

        self.startingcash = self.cash
        self.startingvalue = self.value

        self._lock_orders = threading.Lock()  # control access
        self.orderbyid = dict()  # orders by order id
        self.executions = dict()  # notified executions
        self.ordstatus = collections.defaultdict(dict)
        self.notifs = queue.Queue()  # holds orders which are notified
        self.tonotify = collections.deque()  # hold oids to be notified

    def start(self):
        super().start()
        self.mock_store.start(broker=self)

        # update account cash value
        if self.mock_store.connected():
            self.mock_store.reqAccountUpdates()
            self.startingcash = self.cash = self.mock_store.get_acc_cash()
            self.startingvalue = self.value = self.mock_store.get_acc_value()
        else:
            self.startingcash = self.cash = 0.0
            self.startingvalue = self.value = 0.0

    def stop(self):
        super().stop()
        self.mock_store.stop()

    def getcash(self):
        # This call cannot block if no answer is available from ib
        self.cash = self.mock_store.get_acc_cash()
        return self.cash

    def getvalue(self, datas=None):
        self.value = self.mock_store.get_acc_value()
        return self.value

    def getposition(self, data, clone=True):
        return self.mock_store.getposition(data, clone=clone)

    def cancel(self, order):
        try:
            o = self.orderbyid[order.m_orderId]
        except (ValueError, KeyError):
            return  # not found ... not cancellable

        if order.status == Order.Cancelled:  # already cancelled
            return

        self.mock_store.cancelOrder(order.m_orderId)

    def orderstatus(self, order):
        try:
            o = self.orderbyid[order.m_orderId]
        except (ValueError, KeyError):
            o = order

        return o.status

    def submit(self, order):
        order.submit(self)

        # ocoize if needed
        if order.oco is None:  # Generate a UniqueId
            order.m_ocaGroup = bytes(uuid.uuid4())
        else:
            order.m_ocaGroup = self.orderbyid[order.oco.m_orderId].m_ocaGroup

        self.orderbyid[order.m_orderId] = order
        self.ib.placeOrder(order.m_orderId, order.data.tradecontract, order)
        self.notify(order)

        return order

    def getcommissioninfo(self, data):
        contract = data.tradecontract
        try:
            mult = float(contract.m_multiplier)
        except (ValueError, TypeError):
            mult = 1.0

        stocklike = contract.m_secType not in ('FUT', 'OPT', 'FOP',)

        return IBCommInfo(mult=mult, stocklike=stocklike)

    def _makeorder(self, action, owner, data,
                   size, price=None, plimit=None,
                   exectype=None, valid=None,
                   tradeid=0, **kwargs):

        order = IBOrder(action, owner=owner, data=data,
                        size=size, price=price, pricelimit=plimit,
                        exectype=exectype, valid=valid,
                        tradeid=tradeid,
                        m_clientId=self.ib.clientId,
                        m_orderId=self.ib.nextOrderId(),
                        **kwargs)

        order.addcomminfo(self.getcommissioninfo(data))
        return order

    def buy(self, owner, data,
            size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0,
            **kwargs):

        order = self._makeorder(
            'BUY',
            owner, data, size, price, plimit, exectype, valid, tradeid,
            **kwargs)

        return self.submit(order)

    def sell(self, owner, data,
             size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0,
             **kwargs):

        order = self._makeorder(
            'SELL',
            owner, data, size, price, plimit, exectype, valid, tradeid,
            **kwargs)

        return self.submit(order)

    def notify(self, order):
        self.notifs.put(order.clone())

    def get_notification(self):
        try:
            return self.notifs.get(False)
        except queue.Empty:
            pass

        return None

    def next(self):
        self.notifs.put(None)  # mark notificatino boundary

    # Order statuses in msg
    (SUBMITTED, FILLED, CANCELLED, INACTIVE,
     PENDINGSUBMIT, PENDINGCANCEL, PRESUBMITTED) = (
        'Submitted', 'Filled', 'Cancelled', 'Inactive',
         'PendingSubmit', 'PendingCancel', 'PreSubmitted',)

    def push_orderstatus(self, msg):
        # Cancelled and Submitted with Filled = 0 can be pushed immediately
        try:
            order = self.orderbyid[msg.orderId]
        except KeyError:
            return  # not found, it was not an order

        if msg.status == self.SUBMITTED and msg.filled == 0:
            if order.status == order.Accepted:  # duplicate detection
                return

            order.accept(self)
            self.notify(order)

        elif msg.status == self.CANCELLED:
            # duplicate detection
            if order.status in [order.Cancelled, order.Expired]:
                return

            if order._willexpire:
                # An openOrder has been seen with PendingCancel/Cancelled
                # and this happens when an order expires
                order.expire()
            else:
                # Pure user cancellation happens without an openOrder
                order.cancel()
            self.notify(order)

        elif msg.status == self.PENDINGCANCEL:
            # In theory this message should not be seen according to the docs,
            # but other messages like PENDINGSUBMIT which are similarly
            # described in the docs have been received in the demo
            if order.status == order.Cancelled:  # duplicate detection
                return

            # We do nothing because the situation is handled with the 202 error
            # code if no orderStatus with CANCELLED is seen
            # order.cancel()
            # self.notify(order)

        elif msg.status == self.INACTIVE:
            # This is a tricky one, because the instances seen have led to
            # order rejection in the demo, but according to the docs there may
            # be a number of reasons and it seems like it could be reactivated
            if order.status == order.Rejected:  # duplicate detection
                return

            order.reject(self)
            self.notify(order)

        elif msg.status in [self.SUBMITTED, self.FILLED]:
            # These two are kept inside the order until execdetails and
            # commission are all in place - commission is the last to come
            self.ordstatus[msg.orderId][msg.filled] = msg

        elif msg.status in [self.PENDINGSUBMIT, self.PRESUBMITTED]:
            # According to the docs, these statuses can only be set by the
            # programmer but the demo account sent it back at random times with
            # "filled"
            if msg.filled:
                self.ordstatus[msg.orderId][msg.filled] = msg
        else:  # Unknown status ...
            pass

    def push_execution(self, ex):
        self.executions[ex.m_execId] = ex

    def push_commissionreport(self, cr):
        with self._lock_orders:
            ex = self.executions.pop(cr.m_execId)
            oid = ex.m_orderId
            order = self.orderbyid[oid]
            ostatus = self.ordstatus[oid].pop(ex.m_cumQty)

            position = self.getposition(order.data, clone=False)
            pprice_orig = position.price
            size = ex.m_shares if ex.m_side[0] == 'B' else -ex.m_shares
            price = ex.m_price
            # use pseudoupdate and let the updateportfolio do the real update?
            psize, pprice, opened, closed = position.update(size, price)

            # split commission between closed and opened
            comm = cr.m_commission
            closedcomm = comm * closed / size
            openedcomm = comm - closedcomm

            comminfo = order.comminfo
            closedvalue = comminfo.getoperationcost(closed, pprice_orig)
            openedvalue = comminfo.getoperationcost(opened, price)

            # default in m_pnl is MAXFLOAT
            pnl = cr.m_realizedPNL if closed else 0.0

            # The internal broker calc should yield the same result
            # pnl = comminfo.profitandloss(-closed, pprice_orig, price)

            # Use the actual time provided by the execution object
            # The report from TWS is in actual local time, not the data's tz
            dt = date2num(datetime.strptime(ex.m_time, '%Y%m%d  %H:%M:%S'))

            # Need to simulate a margin, but it plays no role, because it is
            # controlled by a real broker. Let's set the price of the item
            margin = order.data.close[0]

            order.execute(dt, size, price,
                          closed, closedvalue, closedcomm,
                          opened, openedvalue, openedcomm,
                          margin, pnl,
                          psize, pprice)

            if ostatus.status == self.FILLED:
                order.completed()
                self.ordstatus.pop(oid)  # nothing left to be reported
            else:
                order.partial()

            if oid not in self.tonotify:  # Lock needed
                self.tonotify.append(oid)

    def push_portupdate(self):
        # If the IBStore receives a Portfolio update, then this method will be
        # indicated. If the execution of an order is split in serveral lots,
        # updatePortfolio messages will be intermixed, which is used as a
        # signal to indicate that the strategy can be notified
        with self._lock_orders:
            while self.tonotify:
                oid = self.tonotify.popleft()
                order = self.orderbyid[oid]
                self.notify(order)

    def push_ordererror(self, msg):
        with self._lock_orders:
            try:
                order = self.orderbyid[msg.id]
            except (KeyError, AttributeError):
                return  # no order or no id in error

            if msg.errorCode == 202:
                if not order.alive():
                    return
                order.cancel()

            elif msg.errorCode == 201:  # rejected
                if order.status == order.Rejected:
                    return
                order.reject()

            else:
                order.reject()  # default for all other cases

            self.notify(order)

    def push_orderstate(self, msg):
        with self._lock_orders:
            try:
                order = self.orderbyid[msg.orderId]
            except (KeyError, AttributeError):
                return  # no order or no id in error

            if msg.orderState.m_status in ['PendingCancel', 'Cancelled',
                                           'Canceled']:
                # This is most likely due to an expiration]
                order._willexpire = True
