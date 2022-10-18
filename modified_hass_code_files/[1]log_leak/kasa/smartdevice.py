"""Python library supporting TP-Link Smart Home devices.

The communication protocol was reverse engineered by Lubomir Stroetmann and
Tobias Esser in 'Reverse Engineering the TP-Link HS110':
https://www.softscheck.com/en/reverse-engineering-tp-link-hs110/

This library reuses codes and concepts of the TP-Link WiFi SmartPlug Client
at https://github.com/softScheck/tplink-smartplug, developed by Lubomir
Stroetmann which is licensed under the Apache License, Version 2.0.

You may obtain a copy of the license at
http://www.apache.org/licenses/LICENSE-2.0
"""
import collections.abc
import functools
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

from .emeterstatus import EmeterStatus
from .exceptions import SmartDeviceException
from .modules import Emeter, Module
from .protocol import TPLinkSmartHomeProtocol


_LOGGER = logging.getLogger(__name__)


class DeviceType(Enum):
    """Device type enum."""

    Plug = auto()
    Bulb = auto()
    Strip = auto()
    StripSocket = auto()
    Dimmer = auto()
    LightStrip = auto()
    Unknown = -1

    _LOGGER.info(f"CustomLog || Kasa || DeviceType class || NA || Device details - Plug: {Plug} ; Bulb: {Bulb} ; Strip: {Strip} ; StripSocket: {StripSocket} ; Dimmer: {Dimmer} ; LightStrip: {LightStrip}")


@dataclass
class WifiNetwork:
    """Wifi network container."""

    ssid: str
    key_type: int
    # These are available only on softaponboarding
    cipher_type: Optional[int] = None
    bssid: Optional[str] = None
    channel: Optional[int] = None
    rssi: Optional[int] = None


def merge(d, u):
    """Update dict recursively."""

    _LOGGER.info("CustomLog || Kasa || WifiNetwork class || merge method")

    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = merge(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def requires_update(f):
    """Indicate that `update` should be called before accessing this method."""  # noqa: D202

    _LOGGER.info("CustomLog || Kasa || WifiNetwork class || requires_update method")

    if inspect.iscoroutinefunction(f):

        @functools.wraps(f)
        async def wrapped(*args, **kwargs):
            self = args[0]
            if self._last_update is None:
                raise SmartDeviceException(
                    "You need to await update() to access the data"
                )
            return await f(*args, **kwargs)

    else:

        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            self = args[0]
            if self._last_update is None:
                raise SmartDeviceException(
                    "You need to await update() to access the data"
                )
            return f(*args, **kwargs)

    f.requires_update = True
    return wrapped


class SmartDevice:
    """Base class for all supported device types.

    You don't usually want to construct this class which implements the shared common interfaces.
    The recommended way is to either use the discovery functionality, or construct one of the subclasses:

    * :class:`SmartPlug`
    * :class:`SmartBulb`
    * :class:`SmartStrip`
    * :class:`SmartDimmer`
    * :class:`SmartLightStrip`

    To initialize, you have to await :func:`update()` at least once.
    This will allow accessing the properties using the exposed properties.

    All changes to the device are done using awaitable methods,
    which will not change the cached values, but you must await update() separately.

    Errors reported by the device are raised as SmartDeviceExceptions,
    and should be handled by the user of the library.

    Examples:
        >>> import asyncio
        >>> dev = SmartDevice("127.0.0.1")
        >>> asyncio.run(dev.update())

        All devices provide several informational properties:

        >>> dev.alias
        Kitchen
        >>> dev.model
        HS110(EU)
        >>> dev.rssi
        -71
        >>> dev.mac
        50:C7:BF:01:F8:CD

        Some information can also be changed programatically:

        >>> asyncio.run(dev.set_alias("new alias"))
        >>> asyncio.run(dev.set_mac("01:23:45:67:89:ab"))
        >>> asyncio.run(dev.update())
        >>> dev.alias
        new alias
        >>> dev.mac
        01:23:45:67:89:ab

        When initialized using discovery or using a subclass, you can check the type of the device:

        >>> dev.is_bulb
        False
        >>> dev.is_strip
        False
        >>> dev.is_plug
        True

        You can also get the hardware and software as a dict, or access the full device response:

        >>> dev.hw_info
        {'sw_ver': '1.2.5 Build 171213 Rel.101523',
         'hw_ver': '1.0',
         'mac': '01:23:45:67:89:ab',
         'type': 'IOT.SMARTPLUGSWITCH',
         'hwId': '45E29DA8382494D2E82688B52A0B2EB5',
         'fwId': '00000000000000000000000000000000',
         'oemId': '3D341ECE302C0642C99E31CE2430544B',
         'dev_name': 'Wi-Fi Smart Plug With Energy Monitoring'}
        >>> dev.sys_info

        All devices can be turned on and off:

        >>> asyncio.run(dev.turn_off())
        >>> asyncio.run(dev.turn_on())
        >>> asyncio.run(dev.update())
        >>> dev.is_on
        True

        Some devices provide energy consumption meter, and regular update will already fetch some information:

        >>> dev.has_emeter
        True
        >>> dev.emeter_realtime
        <EmeterStatus power=0.983971 voltage=235.595234 current=0.015342 total=32.448>
        >>> dev.emeter_today
        >>> dev.emeter_this_month

        You can also query the historical data (note that these needs to be awaited), keyed with month/day:

        >>> asyncio.run(dev.get_emeter_monthly(year=2016))
        {11: 1.089, 12: 1.582}
        >>> asyncio.run(dev.get_emeter_daily(year=2016, month=11))
        {24: 0.026, 25: 0.109}

    """

    emeter_type = "emeter"

    def __init__(self, host: str) -> None:
        """Create a new SmartDevice instance.

        :param str host: host name or ip address on which the device listens
        """
        self.host = host

        self.protocol = TPLinkSmartHomeProtocol(host)
        _LOGGER.debug("Initializing %s of type %s", self.host, type(self))
        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || __init__ method || Initializing host [{self.host}] of type {type(self)}")

        self._device_type = DeviceType.Unknown
        # TODO: typing Any is just as using Optional[Dict] would require separate checks in
        #       accessors. the @updated_required decorator does not ensure mypy that these
        #       are not accessed incorrectly.
        self._last_update: Any = None
        self._sys_info: Any = None  # TODO: this is here to avoid changing tests
        self.modules: Dict[str, Any] = {}

        self.children: List["SmartDevice"] = []

    def add_module(self, name: str, module: Module):
        """Register a module."""
        if name in self.modules:
            _LOGGER.debug("Module %s already registered, ignoring..." % name)
            _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || add_module method || Ignoring module {name} since it is already registered")
            return

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || add_module method || Registering module: {name not in self.modules}")

        assert name not in self.modules

        _LOGGER.debug("Adding module %s", module)
        self.modules[name] = module

    def _create_request(
        self, target: str, cmd: str, arg: Optional[Dict] = None, child_ids=None
    ):

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || _create_request method")

        request: Dict[str, Any] = {target: {cmd: arg}}
        if child_ids is not None:
            request = {"context": {"child_ids": child_ids}, target: {cmd: arg}}

            _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || _create_request method || Request - {request}")

        return request

    def _verify_emeter(self) -> None:
        """Raise an exception if there is no emeter."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || _verify_emeter method || has_emeter? {self.has_emeter}")

        if not self.has_emeter:
            raise SmartDeviceException("Device has no emeter")
        if self.emeter_type not in self._last_update:
            raise SmartDeviceException("update() required prior accessing emeter")

    async def _query_helper(
        self, target: str, cmd: str, arg: Optional[Dict] = None, child_ids=None
    ) -> Any:
        """Query device, return results or raise an exception.

        :param target: Target system {system, time, emeter, ..}
        :param cmd: Command to execute
        :param arg: payload dict to be send to the device
        :param child_ids: ids of child devices
        :return: Unwrapped result for the call.
        """
        request = self._create_request(target, cmd, arg, child_ids)

        try:
            response = await self.protocol.query(request=request)
        except Exception as ex:
            raise SmartDeviceException(f"Communication error on {target}:{cmd}") from ex

        if target not in response:
            raise SmartDeviceException(f"No required {target} in response: {response}")

        result = response[target]
        if "err_code" in result and result["err_code"] != 0:
            raise SmartDeviceException(f"Error on {target}.{cmd}: {result}")

        if cmd not in result:
            raise SmartDeviceException(f"No command in response: {response}")
        result = result[cmd]
        if "err_code" in result and result["err_code"] != 0:
            raise SmartDeviceException(f"Error on {target} {cmd}: {result}")

        if "err_code" in result:
            del result["err_code"]

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || _query_helper method || Request - {request}")        

        return result

    @property  # type: ignore
    @requires_update
    def features(self) -> Set[str]:
        """Return a set of features that the device supports."""
        try:

            _LOGGER.info("CustomLog || Kasa || SmartDevice class || features method || Features: %s", set(self.sys_info["feature"].split(":")))  

            return set(self.sys_info["feature"].split(":"))
        except KeyError:
            _LOGGER.debug("Device does not have feature information")
            return set()

    @property  # type: ignore
    @requires_update
    def supported_modules(self) -> List[str]:
        """Return a set of modules supported by the device."""
        # TODO: this should rather be called `features`, but we don't want to break
        #       the API now. Maybe just deprecate it and point the users to use this?
        return list(self.modules.keys())

    @property  # type: ignore
    @requires_update
    def has_emeter(self) -> bool:
        """Return True if device has an energy meter."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || has_emeter method || Has energy meter? {'ENE' in self.features}")

        return "ENE" in self.features

    async def get_sys_info(self) -> Dict[str, Any]:
        """Retrieve system information."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || get_sys_info method || System info: %s", self._query_helper("system", "get_sysinfo"))     

        return await self._query_helper("system", "get_sysinfo")

    async def update(self, update_children: bool = True):
        """Query the device to update the data.

        Needed for properties that are decorated with `requires_update`.
        """
        req = {}
        req.update(self._create_request("system", "get_sysinfo"))

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || update method")


        # If this is the initial update, check only for the sysinfo
        # This is necessary as some devices crash on unexpected modules
        # See #105, #120, #161
        if self._last_update is None:
            _LOGGER.debug("Performing the initial update to obtain sysinfo")
            self._last_update = await self.protocol.query(req)
            self._sys_info = self._last_update["system"]["get_sysinfo"]
            _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || update method || Initial system info update: {self._sys_info}")

        await self._modular_update(req)
        self._sys_info = self._last_update["system"]["get_sysinfo"]
        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || update method || Last system info update: {self._sys_info}")


    async def _modular_update(self, req: dict) -> None:
        """Execute an update query."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || _modular_update method")

        if self.has_emeter:
            _LOGGER.debug(
                "The device has emeter, querying its information along sysinfo"
            )
            self.add_module("emeter", Emeter(self, self.emeter_type))

        for module in self.modules.values():
            if not module.is_supported:
                _LOGGER.debug("Module %s not supported, skipping" % module)
                continue
            q = module.query()
            _LOGGER.debug("Adding query for %s: %s", module, q)
            req = merge(req, q)

        self._last_update = await self.protocol.query(req)

    def update_from_discover_info(self, info):
        """Update state from info from the discover call."""
        self._last_update = info
        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || update_from_discover_info method || Info: {self._last_update}")

        self._sys_info = info["system"]["get_sysinfo"]
        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || update_from_discover_info method || Update system info: {self._sys_info}")


    @property  # type: ignore
    @requires_update
    def sys_info(self) -> Dict[str, Any]:
        """Return system information."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || sys_info method || sys_info: {self._sys_info}")

        return self._sys_info  # type: ignore

    @property  # type: ignore
    @requires_update
    def model(self) -> str:
        """Return device model."""
        sys_info = self.sys_info

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || model method || Device model: {str(sys_info['model'])}")

        return str(sys_info["model"])

    @property  # type: ignore
    @requires_update
    def alias(self) -> str:
        """Return device name (alias)."""
        sys_info = self.sys_info

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || alias method || Device alias: {str(sys_info['alias'])}")

        return str(sys_info["alias"])

    async def set_alias(self, alias: str) -> None:
        """Set the device name (alias)."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || set_alias method || alias: %s", self._query_helper("system", "set_dev_alias", {"alias": alias}))

        return await self._query_helper("system", "set_dev_alias", {"alias": alias})

    @property  # type: ignore
    @requires_update
    def time(self) -> datetime:
        """Return current time from the device."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || time method || Device current time: {self.modules['time'].time}")

        return self.modules["time"].time

    @property  # type: ignore
    @requires_update
    def timezone(self) -> Dict:
        """Return the current timezone."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || timezone method || Device current timezone: {self.modules['time'].timezone}")

        return self.modules["time"].timezone

    async def get_time(self) -> Optional[datetime]:
        """Return current time from the device, if available."""
        _LOGGER.warning(
            "Use `time` property instead, this call will be removed in the future."
        )

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || get_time method || Get current device time: {self.modules['time'].get_time()}")

        return await self.modules["time"].get_time()

    async def get_timezone(self) -> Dict:
        """Return timezone information."""
        _LOGGER.warning(
            "Use `timezone` property instead, this call will be removed in the future."
        )

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || get_timezone method || Get current device timezone: {self.modules['time'].get_timezone()}")

        return await self.modules["time"].get_timezone()

    @property  # type: ignore
    @requires_update
    def hw_info(self) -> Dict:
        """Return hardware information.

        This returns just a selection of sysinfo keys that are related to hardware.
        """
        keys = [
            "sw_ver",
            "hw_ver",
            "mac",
            "mic_mac",
            "type",
            "mic_type",
            "hwId",
            "fwId",
            "oemId",
            "dev_name",
        ]

        sys_info = self.sys_info

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || hw_info method || System hardware info: {sys_info}")

        return {key: sys_info[key] for key in keys if key in sys_info}

    @property  # type: ignore
    @requires_update
    def location(self) -> Dict:
        """Return geographical location."""
        sys_info = self.sys_info
        loc = {"latitude": None, "longitude": None}

        if "latitude" in sys_info and "longitude" in sys_info:
            loc["latitude"] = sys_info["latitude"]
            loc["longitude"] = sys_info["longitude"]
            _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || location method || Device coordinates - Latitude: {loc['latitude']} ; Longitude: {loc['longitude']}")            
        elif "latitude_i" in sys_info and "longitude_i" in sys_info:
            loc["latitude"] = sys_info["latitude_i"] / 10000
            loc["longitude"] = sys_info["longitude_i"] / 10000
            _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || location method || Device coordinates - Latitude/10000: {loc['latitude_i']} ; Longitude/10000: {loc['longitude_i']}")                        
        else:
            _LOGGER.debug("Unsupported device location.")

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || location method || Device location: {loc}")           
        return loc

    @property  # type: ignore
    @requires_update
    def rssi(self) -> Optional[int]:
        """Return WiFi signal strenth (rssi)."""
        rssi = self.sys_info.get("rssi")

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || rssi method || WiFi signal strength (RSSI): {None if rssi is None else int(rssi)}")

        return None if rssi is None else int(rssi)

    @property  # type: ignore
    @requires_update
    def mac(self) -> str:
        """Return mac address.

        :return: mac address in hexadecimal with colons, e.g. 01:23:45:67:89:ab
        """
        sys_info = self.sys_info

        mac = sys_info.get("mac", sys_info.get("mic_mac"))
        if not mac:
            raise SmartDeviceException(
                "Unknown mac, please submit a bug report with sys_info output."
            )

        if ":" not in mac:
            mac = ":".join(format(s, "02x") for s in bytes.fromhex(mac))
            _LOGGER.info("CustomLog || Kasa || SmartDevice class || mac method || MAC: %s", mac)            

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || mac method || MAC address: %s", mac)            

        return mac

    async def set_mac(self, mac):
        """Set the mac address.

        :param str mac: mac in hexadecimal with colons, e.g. 01:23:45:67:89:ab
        """

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || set_mac method || Setting MAC: %s", (self._query_helper("system", "set_mac_addr", {"mac": mac})))

        return await self._query_helper("system", "set_mac_addr", {"mac": mac})

    @property  # type: ignore
    @requires_update
    def emeter_realtime(self) -> EmeterStatus:
        """Return current energy readings."""
        self._verify_emeter()

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || emeter_realtime method || Current energy readings: {EmeterStatus(self.modules['emeter'].realtime)}")

        return EmeterStatus(self.modules["emeter"].realtime)

    async def get_emeter_realtime(self) -> EmeterStatus:
        """Retrieve current energy readings."""
        self._verify_emeter()

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || get_emeter_realtime method || Get current energy readings: {EmeterStatus(self.modules['emeter'].get_realtime())}")

        return EmeterStatus(await self.modules["emeter"].get_realtime())

    @property  # type: ignore
    @requires_update
    def emeter_today(self) -> Optional[float]:
        """Return today's energy consumption in kWh."""
        self._verify_emeter()

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || emeter_today method || Today's energy consumption: {self.modules['emeter'].emeter_today}kWh")

        return self.modules["emeter"].emeter_today

    @property  # type: ignore
    @requires_update
    def emeter_this_month(self) -> Optional[float]:
        """Return this month's energy consumption in kWh."""
        self._verify_emeter()

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || emeter_today method || This month's energy consumption: {self.modules['emeter'].emeter_this_month}kWh")

        return self.modules["emeter"].emeter_this_month

    def _emeter_convert_emeter_data(self, data, kwh=True) -> Dict:
        """Return emeter information keyed with the day/month.."""
        response = [EmeterStatus(**x) for x in data]

        if not response:
            return {}

        energy_key = "energy_wh"
        if kwh:
            energy_key = "energy"

        entry_key = "month"
        if "day" in response[0]:
            entry_key = "day"

        data = {entry[entry_key]: entry[energy_key] for entry in response}

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || _emeter_convert_emeter_data method || Return emeter information: {data}")

        return data

    async def get_emeter_daily(
        self, year: int = None, month: int = None, kwh: bool = True
    ) -> Dict:
        """Retrieve daily statistics for a given month.

        :param year: year for which to retrieve statistics (default: this year)
        :param month: month for which to retrieve statistics (default: this
                      month)
        :param kwh: return usage in kWh (default: True)
        :return: mapping of day of month to value
        """
        self._verify_emeter()

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || get_emeter_daily method || Daily stats for the month: %s", (self.modules["emeter"].get_daystat(year=year, month=month, kwh=kwh)))

        return await self.modules["emeter"].get_daystat(year=year, month=month, kwh=kwh)

    @requires_update
    async def get_emeter_monthly(self, year: int = None, kwh: bool = True) -> Dict:
        """Retrieve monthly statistics for a given year.

        :param year: year for which to retrieve statistics (default: this year)
        :param kwh: return usage in kWh (default: True)
        :return: dict: mapping of month to value
        """
        self._verify_emeter()

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || get_emeter_daily method || Monthly stats for the year: %s", (self.modules["emeter"].get_monthstat(year=year, kwh=kwh)))

        return await self.modules["emeter"].get_monthstat(year=year, kwh=kwh)

    @requires_update
    async def erase_emeter_stats(self) -> Dict:
        """Erase energy meter statistics."""
        self._verify_emeter()

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || erase_emeter_stats method")        

        return await self.modules["emeter"].erase_stats()

    @requires_update
    async def current_consumption(self) -> float:
        """Get the current power consumption in Watt."""
        self._verify_emeter()
        response = self.emeter_realtime

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || current_consumption method || Current power consumption: {float(response['power'])}W")        

        return float(response["power"])

    async def reboot(self, delay: int = 1) -> None:
        """Reboot the device.

        Note that giving a delay of zero causes this to block,
        as the device reboots immediately without responding to the call.
        """

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || reboot method")        

        await self._query_helper("system", "reboot", {"delay": delay})

    async def turn_off(self, **kwargs) -> Dict:
        """Turn off the device."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || turn_off method")        

        raise NotImplementedError("Device subclass needs to implement this.")

    @property  # type: ignore
    @requires_update
    def is_off(self) -> bool:
        """Return True if device is off."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || is_off method || Is device off? {not self.is_on}")        

        return not self.is_on

    async def turn_on(self, **kwargs) -> Dict:
        """Turn device on."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || turn_on method")        

        raise NotImplementedError("Device subclass needs to implement this.")

    @property  # type: ignore
    @requires_update
    def is_on(self) -> bool:
        """Return True if the device is on."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_on method")        

        raise NotImplementedError("Device subclass needs to implement this.")

    @property  # type: ignore
    @requires_update
    def on_since(self) -> Optional[datetime]:
        """Return pretty-printed on-time, or None if not available."""
        if "on_time" not in self.sys_info:
            return None

        if self.is_off:
            return None

        on_time = self.sys_info["on_time"]

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || on_since method || on_time: {on_time}") 
        _LOGGER.info("CustomLog || Kasa || SmartDevice class || on_since method || Device on_since: %s", (datetime.now().replace(microsecond=0) - timedelta(seconds=on_time))) 

        return datetime.now().replace(microsecond=0) - timedelta(seconds=on_time)

    @property  # type: ignore
    @requires_update
    def state_information(self) -> Dict[str, Any]:
        """Return device-type specific, end-user friendly state information."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || state_information method")        

        raise NotImplementedError("Device subclass needs to implement this.")

    @property  # type: ignore
    @requires_update
    def device_id(self) -> str:
        """Return unique ID for the device.

        If not overridden, this is the MAC address of the device.
        Individual sockets on strips will override this.
        """
        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || device_id method || Device unique ID (MAC): {self.mac}")        

        return self.mac

    async def wifi_scan(self) -> List[WifiNetwork]:  # noqa: D202
        """Scan for available wifi networks."""

        async def _scan(target):

            _LOGGER.info("CustomLog || Kasa || SmartDevice class || wifi_scan method >> _scan method || Scan: %s", (self._query_helper(target, "get_scaninfo", {"refresh": 1})))             

            return await self._query_helper(target, "get_scaninfo", {"refresh": 1})

        try:
            info = await _scan("netif")
        except SmartDeviceException as ex:
            _LOGGER.debug(
                "Unable to scan using 'netif', retrying with 'softaponboarding': %s", ex
            )
            info = await _scan("smartlife.iot.common.softaponboarding")

        if "ap_list" not in info:
            raise SmartDeviceException("Invalid response for wifi scan: %s" % info)

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || wifi_scan method || WifiNetwork: %s", ([WifiNetwork(**x) for x in info["ap_list"]]))

        return [WifiNetwork(**x) for x in info["ap_list"]]

    async def wifi_join(self, ssid, password, keytype=3):  # noqa: D202
        """Join the given wifi network.

        If joining the network fails, the device will return to AP mode after a while.
        """

        async def _join(target, payload):

            _LOGGER.info("CustomLog || Kasa || SmartDevice class || wifi_join method >> _join method || Join: %s", (self._query_helper(target, "set_stainfo", payload)))            

            return await self._query_helper(target, "set_stainfo", payload)

        payload = {"ssid": ssid, "password": password, "key_type": keytype}

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || wifi_join method || Payload: {payload}") 

        try:
            return await _join("netif", payload)
        except SmartDeviceException as ex:
            _LOGGER.debug(
                "Unable to join using 'netif', retrying with 'softaponboarding': %s", ex
            )
            return await _join("smartlife.iot.common.softaponboarding", payload)

    def get_plug_by_name(self, name: str) -> "SmartDevice":
        """Return child device for the given name."""
        for p in self.children:
            if p.alias == name:
                _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || get_plug_by_name method || Plug child device: {p}")            
                return p

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || get_plug_by_name method || Plug name: {name}")            

        raise SmartDeviceException(f"Device has no child with {name}")

    def get_plug_by_index(self, index: int) -> "SmartDevice":
        """Return child device for the given index."""
        if index + 1 > len(self.children) or index < 0:
            raise SmartDeviceException(
                f"Invalid index {index}, device has {len(self.children)} plugs"
            )

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || get_plug_by_index method || Child device index: {self.children[index]}")            

        return self.children[index]

    @property
    def device_type(self) -> DeviceType:
        """Return the device type."""

        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || device_type method || Device type: {self._device_type}")            

        return self._device_type

    @property
    def is_bulb(self) -> bool:
        """Return True if the device is a bulb."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_bulb method")

        return self._device_type == DeviceType.Bulb

    @property
    def is_light_strip(self) -> bool:
        """Return True if the device is a led strip."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_light_strip method")

        return self._device_type == DeviceType.LightStrip

    @property
    def is_plug(self) -> bool:
        """Return True if the device is a plug."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_plug method")

        return self._device_type == DeviceType.Plug

    @property
    def is_strip(self) -> bool:
        """Return True if the device is a strip."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_strip method")

        return self._device_type == DeviceType.Strip

    @property
    def is_strip_socket(self) -> bool:
        """Return True if the device is a strip socket."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_strip_socket method")

        return self._device_type == DeviceType.StripSocket

    @property
    def is_dimmer(self) -> bool:
        """Return True if the device is a dimmer."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_dimmer method")

        return self._device_type == DeviceType.Dimmer

    @property
    def is_dimmable(self) -> bool:
        """Return  True if the device is dimmable."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_dimmable method")

        return False

    @property
    def is_variable_color_temp(self) -> bool:
        """Return True if the device supports color temperature."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_variable_color_temp method")        

        return False

    @property
    def is_color(self) -> bool:
        """Return True if the device supports color changes."""

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || is_color method")        

        return False

    @property
    def internal_state(self) -> Any:
        """Return the internal state of the instance.

        The returned object contains the raw results from the last update call.
        This should only be used for debugging purposes.
        """
        return self._last_update

    def __repr__(self):

        _LOGGER.info("CustomLog || Kasa || SmartDevice class || __repr__ method")        

        if self._last_update is None:
            _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || __repr__ method || No last update: <{self._device_type} at {self.host} - update needed>")        
            return f"<{self._device_type} at {self.host} - update() needed>"

        deviceType = self._device_type
        deviceIsOn = self.is_on
        deviceOnSince = self.on_since

        #write to homeassistant's logfile
        _LOGGER.info(f"CustomLog || Kasa || SmartDevice class || __repr__ method || Last update: {deviceType} of model {self.model} has IP {self.host}, and alias {self.alias} // is_on? {deviceIsOn} since {deviceOnSince} // device state info: {self.state_information}")

        return f"<{self._device_type} model {self.model} at {self.host} ({self.alias}), is_on: {self.is_on} - dev specific: {self.state_information}>"
