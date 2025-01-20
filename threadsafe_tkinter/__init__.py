'''
This is a thread-safe version of Tkinter for Python3.
Import this where you would normally import tkinter.


Copyright (c) 2017 Devin Bobadilla

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
'''
# ##############
#   metadata   #
# ##############
__author__ = "Devin Bobadilla"
#           YYYY.MM.DD
__date__ = "2025.01.18"
__version__ = (1, 0, 5)

try:
    from tkinter import *
except ImportError:
    from Tkinter import *
from queue import Queue as _Queue, Empty as _Empty
try:
    from threading import currentThread as _curr_thread, _DummyThread
except ImportError:
    from threading import current_thread as _curr_thread, _DummyThread

from types import FunctionType

TKHOOK_UNHOOKING = -1
TKHOOK_UNHOOKED = 0
TKHOOK_HOOKED = 1


class TkWrapper:
    # process ~90 times per second(aiming for 90Hz with some wiggle room)
    idle_time = 11  # process requests every 11 milliseconds
    after_call_id = None
    _hook_status = TKHOOK_UNHOOKED

    def __init__(self, tk_widget=None):
        self.tk_widget     = tk_widget
        self.request_queue = self.create_queue()
        self.tk_thread     = self.get_curr_thread()
        self.after_call_id = None

    # change these if your application uses a different threading framework.
    def get_curr_thread(self):      return _curr_thread()
    def create_queue(self, size=0): return _Queue(size)

    def __getattr__(self, attr_name):
        if self.tk_widget is None or self.tk_widget._tk is None:
            raise AttributeError(
                "self.tk_widget is None. Not hooked into a Tk instance.")

        tk_attr = getattr(self.tk_widget._tk, attr_name)
        return (lambda *a, _f=tk_attr, **kw:
                self.call_tk_attr_threadsafe(_f, *a, **kw))

    def call_tk_attr_threadsafe(self, tk_attr, *a, **kw):
        thread = self.get_curr_thread()
        if thread == self.tk_thread or isinstance(thread, _DummyThread):
            # it is either safe to call from the thread the tkinter widget
            # is running on, or a dummy thread is running which is also safe
            return tk_attr(*a, **kw)

        # add a request to the requests queue to call this attribute
        response_queue = self.create_queue(1)
        result, raise_result = None, None

        self.request_queue.put((response_queue, tk_attr, a, kw))
        while result is None and self.tk_widget is not None:
            try:
                response = response_queue.get(True, 3)
                result, raise_result = response
            except _Empty:
                pass

        if raise_result:
            raise result
        return result

    def hook(self, tk_widget=None):
        if tk_widget is None:
            tk_widget = self.tk_widget

        if tk_widget is None or hasattr(tk_widget, "_tk"):
            return
        elif self._hook_status == TKHOOK_HOOKED:
            return

        self.tk_widget = tk_widget
        tk_widget._tk  = tk_widget.tk
        tk_widget.tk   = self
        self._hook_status = TKHOOK_HOOKED
        self.after_call_id = tk_widget.after(0, self.process_requests)

    def unhook(self):
        if not hasattr(self.tk_widget, "_tk"):
            return
        elif self._hook_status != TKHOOK_HOOKED:
            return
        elif self.after_call_id is None:
            self.tk_widget.tk = self.tk_widget._tk
            self._hook_status = TKHOOK_UNHOOKED
            del self.tk_widget._tk
            self.tk_widget = None
        else:
            self._hook_status = TKHOOK_UNHOOKING

    def process_requests(self):
        # cleanup will be set to True when the wrapper is unhooking. This
        # will force the loop to finish processing requests before it ends.
        cleanup = True
        while cleanup or not self.request_queue.empty():
            cleanup = False
            try:
                response_queue = None
                while (self.tk_widget is not None and
                       self._hook_status != TKHOOK_UNHOOKED) or cleanup:
                    response_queue = None
                    # get the response container, function and args, call
                    # the function and place the result into the response
                    item = self.request_queue.get_nowait()
                    response_queue, func, a, kw = item
                    result = func(*a, **kw)
                    response_queue.put((result, False))

            except _Empty:
                # nothing to process. break out of loop
                pass
            except Exception as e:
                if response_queue is not None:
                    response_queue.put((e, True))

            if self._hook_status == TKHOOK_UNHOOKING:
                self.tk_widget.tk = self.tk_widget._tk
                self._hook_status = TKHOOK_UNHOOKED
                del self.tk_widget._tk
                self.after_call_id = self.tk_widget = None
                cleanup = True

        if self._hook_status == TKHOOK_HOOKED and self.tk_widget is not None:
            # start another callback next time we can process
            self.after_call_id = self.tk_widget.after(
                self.idle_time, self.process_requests
                )


def _tk_init_override(self, *a, **kw):
    self._orig_init(*a, **kw)
    if not hasattr(self.tk, "hook"):
        # replace the underlying tk object with the wrapper
        TkWrapper().hook(self)

def _tk_destroy_override(self, *a, **kw):
    commands_to_cancel = self.tk.tk_widget._tclCommands
    self._orig_destroy(*a, **kw)
    if hasattr(self.tk, "unhook"):
        # unhook the tk object wrapper
        self.tk.unhook()

    # to ensure no lingering commands attempt to run, we cancel them
    for cmd in commands_to_cancel[::-1]:
        self.tk_widget.after_cancel(cmd)



# dont hook twice or we'll end up with an infinite loop
if not hasattr(Tk, "_orig_init"):
    Tk._orig_init = Tk.__init__
    Tk.__init__   = _tk_init_override


if not hasattr(Tk, "_orig_destroy"):
    Tk._orig_destroy = Tk.destroy
    Tk.destroy       = _tk_destroy_override
