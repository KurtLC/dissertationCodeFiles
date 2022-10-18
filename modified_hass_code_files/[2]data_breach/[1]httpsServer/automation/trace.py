"""Trace support for automation."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from homeassistant.components.trace import ActionTrace, async_store_trace
from homeassistant.components.trace.const import CONF_STORED_TRACES
from homeassistant.core import Context

from .const import DOMAIN

import logging
from threading import Thread
from time import sleep
from requests import post as reqpost, exceptions as reqexc
from urllib3 import exceptions as lib3exc
from warnings import filterwarnings


#mypy: allow-untyped-calls, allow-untyped-defs
#mypy: no-check-untyped-defs, no-warn-return-any


#server IP
serverhostname = "192.168.5.9"
#server port
serverport = 8443
#server URL
serverurl = "https://"+serverhostname+":"+str(serverport)
#thread timeout value
contimeout = 1

_LOGGER = logging.getLogger(__name__)


class AutomationTrace(ActionTrace):
    """Container for automation trace."""

    _domain = DOMAIN

    def __init__(
        self,
        item_id: str,
        config: dict[str, Any],
        blueprint_inputs: dict[str, Any],
        context: Context,
    ) -> None:
        """Container for automation trace."""
        super().__init__(item_id, config, blueprint_inputs, context)
        self._trigger_description: str | None = None
        _LOGGER.info(f"CustomLog || Automation || AutomationTrace class || __init__ method") 


    def set_trigger_description(self, trigger: str) -> None:
        """Set trigger description."""
        self._trigger_description = trigger

        _LOGGER.info(f"CustomLog || Automation || AutomationTrace class || set_trigger_description method || trigger description: {self._trigger_description}")        

    def as_short_dict(self) -> dict[str, Any]:
        """Return a brief dictionary version of this AutomationTrace."""
        if self._short_dict:
            _LOGGER.info(f"CustomLog || Automation || AutomationTrace class || as_short_dict method || {self._short_dict}")
            return self._short_dict

        result = super().as_short_dict()
        result["trigger"] = self._trigger_description

        _LOGGER.info(f"CustomLog || Automation || AutomationTrace class || as_short_dict method || trigger description: {result['trigger']}")

        return result


@contextmanager
def trace_automation(
    hass, automation_id, config, blueprint_inputs, context, trace_config
):
    """Trace action execution of automation with automation_id."""
    trace = AutomationTrace(automation_id, config, blueprint_inputs, context)
    async_store_trace(hass, trace, trace_config[CONF_STORED_TRACES])

    #write to homeassistant's logfile
    _LOGGER.info(f"CustomLog || Automation || AutomationTrace class || trace_automation method || trace info - automation_id: {automation_id} ; config: {config} ; blueprint_inputs: {blueprint_inputs} ; context: {context}") 

    #define message
    message = {'trace':[{'automation_id':str(automation_id)},{'automation_config':str(config)},{'blueprint_inputs':str(blueprint_inputs)},{'context':str(context)}]}
    #set request headers to json
    requestheaders = {'content-type': 'application/json'}

    def logTraceServer():
        try:
            # delay the program execution for a second
            sleep(1)
            #ignore warnings particularly those relating to the untrusted certificate
            filterwarnings('ignore')
            #send POST request with json-formatted message to the server and ignore certificate validation
            reqpost(serverurl, json=message, headers=requestheaders, timeout=contimeout, verify=False)
        except (ConnectionError, lib3exc.HTTPError, reqexc.ConnectionError): #catch any Connection or Protocol errors
            pass #a null statement to continue executing the program and ignore any raised exceptions

    #define a list where one or more instances of the Thread are created
    logtrace = Thread(target=logTraceServer)        
    #start the thread
    logtrace.start()
    #wait for the thread to terminate
    logtrace.join(timeout=contimeout) #set thread to timeout

    try:
        yield trace
    except Exception as ex:
        if automation_id:
            trace.set_error(ex)
        raise ex
    finally:
        if automation_id:
            trace.finished()
