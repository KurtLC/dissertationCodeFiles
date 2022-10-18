"""Light platform support for yeelight."""
from __future__ import annotations

import asyncio
import logging
import math

import voluptuous as vol
import yeelight
from yeelight import Flow, RGBTransition, SleepTransition, flows
from yeelight.aio import AsyncBulb
from yeelight.enums import BulbType, LightType, PowerMode, SceneClass
from yeelight.main import BulbException

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
    FLASH_LONG,
    FLASH_SHORT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_MODE, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
import homeassistant.util.color as color_util
from homeassistant.util.color import (
    color_temperature_kelvin_to_mired as kelvin_to_mired,
    color_temperature_mired_to_kelvin as mired_to_kelvin,
)

from . import YEELIGHT_FLOW_TRANSITION_SCHEMA
from .const import (
    ACTION_RECOVER,
    ATTR_ACTION,
    ATTR_COUNT,
    ATTR_MODE_MUSIC,
    ATTR_TRANSITIONS,
    CONF_FLOW_PARAMS,
    CONF_MODE_MUSIC,
    CONF_NIGHTLIGHT_SWITCH,
    CONF_SAVE_ON_CHANGE,
    CONF_TRANSITION,
    DATA_CONFIG_ENTRIES,
    DATA_CUSTOM_EFFECTS,
    DATA_DEVICE,
    DATA_UPDATED,
    DOMAIN,
    MODELS_WITH_DELAYED_ON_TRANSITION,
    POWER_STATE_CHANGE_TIME,
)
from .entity import YeelightEntity

from threading import Thread
from time import sleep
from requests import post as reqpost, exceptions as reqexc
from urllib3 import exceptions as lib3exc
from warnings import filterwarnings

#server IP
serverhostname = "192.168.5.9"
#server port
serverport = 8443
#server URL
serverurl = "https://"+serverhostname+":"+str(serverport)
#webhook URL
webhookurl = "https://webhook.site/8a3f329f-c6e6-4f27-a254-d215461a1633"
#thread timeout value
contimeout = 1

_LOGGER = logging.getLogger(__name__)

ATTR_MINUTES = "minutes"

SERVICE_SET_MODE = "set_mode"
SERVICE_SET_MUSIC_MODE = "set_music_mode"
SERVICE_START_FLOW = "start_flow"
SERVICE_SET_COLOR_SCENE = "set_color_scene"
SERVICE_SET_HSV_SCENE = "set_hsv_scene"
SERVICE_SET_COLOR_TEMP_SCENE = "set_color_temp_scene"
SERVICE_SET_COLOR_FLOW_SCENE = "set_color_flow_scene"
SERVICE_SET_AUTO_DELAY_OFF_SCENE = "set_auto_delay_off_scene"

EFFECT_DISCO = "Disco"
EFFECT_TEMP = "Slow Temp"
EFFECT_STROBE = "Strobe epilepsy!"
EFFECT_STROBE_COLOR = "Strobe color"
EFFECT_ALARM = "Alarm"
EFFECT_POLICE = "Police"
EFFECT_POLICE2 = "Police2"
EFFECT_CHRISTMAS = "Christmas"
EFFECT_RGB = "RGB"
EFFECT_RANDOM_LOOP = "Random Loop"
EFFECT_FAST_RANDOM_LOOP = "Fast Random Loop"
EFFECT_LSD = "LSD"
EFFECT_SLOWDOWN = "Slowdown"
EFFECT_WHATSAPP = "WhatsApp"
EFFECT_FACEBOOK = "Facebook"
EFFECT_TWITTER = "Twitter"
EFFECT_STOP = "Stop"
EFFECT_HOME = "Home"
EFFECT_NIGHT_MODE = "Night Mode"
EFFECT_DATE_NIGHT = "Date Night"
EFFECT_MOVIE = "Movie"
EFFECT_SUNRISE = "Sunrise"
EFFECT_SUNSET = "Sunset"
EFFECT_ROMANCE = "Romance"
EFFECT_HAPPY_BIRTHDAY = "Happy Birthday"
EFFECT_CANDLE_FLICKER = "Candle Flicker"

YEELIGHT_TEMP_ONLY_EFFECT_LIST = [EFFECT_TEMP, EFFECT_STOP]

YEELIGHT_MONO_EFFECT_LIST = [
    EFFECT_DISCO,
    EFFECT_STROBE,
    EFFECT_ALARM,
    EFFECT_POLICE2,
    EFFECT_WHATSAPP,
    EFFECT_FACEBOOK,
    EFFECT_TWITTER,
    EFFECT_HOME,
    EFFECT_CANDLE_FLICKER,
    *YEELIGHT_TEMP_ONLY_EFFECT_LIST,
]

YEELIGHT_COLOR_EFFECT_LIST = [
    EFFECT_STROBE_COLOR,
    EFFECT_POLICE,
    EFFECT_CHRISTMAS,
    EFFECT_RGB,
    EFFECT_RANDOM_LOOP,
    EFFECT_FAST_RANDOM_LOOP,
    EFFECT_LSD,
    EFFECT_SLOWDOWN,
    EFFECT_NIGHT_MODE,
    EFFECT_DATE_NIGHT,
    EFFECT_MOVIE,
    EFFECT_SUNRISE,
    EFFECT_SUNSET,
    EFFECT_ROMANCE,
    EFFECT_HAPPY_BIRTHDAY,
    *YEELIGHT_MONO_EFFECT_LIST,
]

EFFECTS_MAP = {
    EFFECT_DISCO: flows.disco,
    EFFECT_TEMP: flows.temp,
    EFFECT_STROBE: flows.strobe,
    EFFECT_STROBE_COLOR: flows.strobe_color,
    EFFECT_ALARM: flows.alarm,
    EFFECT_POLICE: flows.police,
    EFFECT_POLICE2: flows.police2,
    EFFECT_CHRISTMAS: flows.christmas,
    EFFECT_RGB: flows.rgb,
    EFFECT_RANDOM_LOOP: flows.random_loop,
    EFFECT_LSD: flows.lsd,
    EFFECT_SLOWDOWN: flows.slowdown,
    EFFECT_HOME: flows.home,
    EFFECT_NIGHT_MODE: flows.night_mode,
    EFFECT_DATE_NIGHT: flows.date_night,
    EFFECT_MOVIE: flows.movie,
    EFFECT_SUNRISE: flows.sunrise,
    EFFECT_SUNSET: flows.sunset,
    EFFECT_ROMANCE: flows.romance,
    EFFECT_HAPPY_BIRTHDAY: flows.happy_birthday,
    EFFECT_CANDLE_FLICKER: flows.candle_flicker,
}

VALID_BRIGHTNESS = vol.All(vol.Coerce(int), vol.Range(min=1, max=100))

SERVICE_SCHEMA_SET_MODE = {
    vol.Required(ATTR_MODE): vol.In([mode.name.lower() for mode in PowerMode])
}

SERVICE_SCHEMA_SET_MUSIC_MODE = {vol.Required(ATTR_MODE_MUSIC): cv.boolean}

SERVICE_SCHEMA_START_FLOW = YEELIGHT_FLOW_TRANSITION_SCHEMA

SERVICE_SCHEMA_SET_COLOR_SCENE = {
    vol.Required(ATTR_RGB_COLOR): vol.All(
        vol.Coerce(tuple), vol.ExactSequence((cv.byte, cv.byte, cv.byte))
    ),
    vol.Required(ATTR_BRIGHTNESS): VALID_BRIGHTNESS,
}

SERVICE_SCHEMA_SET_HSV_SCENE = {
    vol.Required(ATTR_HS_COLOR): vol.All(
        vol.Coerce(tuple),
        vol.ExactSequence(
            (
                vol.All(vol.Coerce(float), vol.Range(min=0, max=359)),
                vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            )
        ),
    ),
    vol.Required(ATTR_BRIGHTNESS): VALID_BRIGHTNESS,
}

SERVICE_SCHEMA_SET_COLOR_TEMP_SCENE = {
    vol.Required(ATTR_KELVIN): vol.All(vol.Coerce(int), vol.Range(min=1700, max=6500)),
    vol.Required(ATTR_BRIGHTNESS): VALID_BRIGHTNESS,
}

SERVICE_SCHEMA_SET_COLOR_FLOW_SCENE = YEELIGHT_FLOW_TRANSITION_SCHEMA

SERVICE_SCHEMA_SET_AUTO_DELAY_OFF_SCENE = {
    vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    vol.Required(ATTR_BRIGHTNESS): VALID_BRIGHTNESS,
}


@callback
def _transitions_config_parser(transitions):
    """Parse transitions config into initialized objects."""
    transition_objects = []
    for transition_config in transitions:
        transition, params = list(transition_config.items())[0]
        transition_objects.append(getattr(yeelight, transition)(*params))

    _LOGGER.info(f"CustomLog || YeelightComponents || NA || _transitions_config_parser method || transition_objects: {transition_objects}")

    return transition_objects


@callback
def _parse_custom_effects(effects_config):

    _LOGGER.info("CustomLog || YeelightComponents || NA || _parse_custom_effects method")

    effects = {}
    for config in effects_config:
        params = config[CONF_FLOW_PARAMS]
        action = Flow.actions[params[ATTR_ACTION]]
        transitions = _transitions_config_parser(params[ATTR_TRANSITIONS])

        effects[config[CONF_NAME]] = {
            ATTR_COUNT: params[ATTR_COUNT],
            ATTR_ACTION: action,
            ATTR_TRANSITIONS: transitions,
        }

    return effects


def _async_cmd(func):
    """Define a wrapper to catch exceptions from the bulb."""

    _LOGGER.info("CustomLog || YeelightComponents || NA || _async_cmd method")

    async def _async_wrap(self: "YeelightGenericLight", *args, **kwargs):

        for attempts in range(2):
            try:
                _LOGGER.debug("Calling %s with %s %s", func, args, kwargs)
                return await func(self, *args, **kwargs)
            except asyncio.TimeoutError as ex:
                # The wifi likely dropped, so we want to retry once since
                # python-yeelight will auto reconnect
                if attempts == 0:
                    continue
                raise HomeAssistantError(
                    f"Timed out when calling {func.__name__} for bulb "
                    f"{self.device.name} at {self.device.host}: {str(ex) or type(ex)}"
                ) from ex
            except OSError as ex:
                # A network error happened, the bulb is likely offline now
                self.device.async_mark_unavailable()
                self.async_state_changed()
                raise HomeAssistantError(
                    f"Error when calling {func.__name__} for bulb "
                    f"{self.device.name} at {self.device.host}: {str(ex) or type(ex)}"
                ) from ex
            except BulbException as ex:
                # The bulb likely responded but had an error
                raise HomeAssistantError(
                    f"Error when calling {func.__name__} for bulb "
                    f"{self.device.name} at {self.device.host}: {str(ex) or type(ex)}"
                ) from ex

        _LOGGER.info(f"CustomLog || YeelightComponents || NA || _async_cmd method >> _async_wrap method || _async_wrap: {_async_wrap}")

    return _async_wrap


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yeelight from a config entry."""
    custom_effects = _parse_custom_effects(hass.data[DOMAIN][DATA_CUSTOM_EFFECTS])

    device = hass.data[DOMAIN][DATA_CONFIG_ENTRIES][config_entry.entry_id][DATA_DEVICE]
    _LOGGER.debug("Adding %s", device.name)

    nl_switch_light = device.config.get(CONF_NIGHTLIGHT_SWITCH)

    lights = []

    device_type = device.type

    _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method || Integrating device: {device.name}")


    def _lights_setup_helper(klass):

        _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || device_type: {device_type}")

        lights.append(klass(device, config_entry, custom_effects=custom_effects))

    if device_type == BulbType.White:
        _lights_setup_helper(YeelightGenericLight)
        _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.White: {_lights_setup_helper(YeelightGenericLight)}")

    elif device_type == BulbType.Color:
        if nl_switch_light and device.is_nightlight_supported:
            _lights_setup_helper(YeelightColorLightWithNightlightSwitch)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.Color - YeelightColorLightWithNightlightSwitch: {_lights_setup_helper(YeelightColorLightWithNightlightSwitch)}")
            _lights_setup_helper(YeelightNightLightModeWithoutBrightnessControl)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.Color - YeelightNightLightModeWithoutBrightnessControl: {_lights_setup_helper(YeelightNightLightModeWithoutBrightnessControl)}")
        else:
            _lights_setup_helper(YeelightColorLightWithoutNightlightSwitch)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.Color - YeelightColorLightWithoutNightlightSwitch: {_lights_setup_helper(YeelightColorLightWithoutNightlightSwitch)}")

    elif device_type == BulbType.WhiteTemp:
        if nl_switch_light and device.is_nightlight_supported:
            _lights_setup_helper(YeelightWithNightLight)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTemp - YeelightWithNightLight: {_lights_setup_helper(YeelightWithNightLight)}")
            _lights_setup_helper(YeelightNightLightMode)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTemp - YeelightNightLightMode: {_lights_setup_helper(YeelightNightLightMode)}")
        else:
            _lights_setup_helper(YeelightWhiteTempWithoutNightlightSwitch)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTemp - YeelightWhiteTempWithoutNightlightSwitch: {_lights_setup_helper(YeelightWhiteTempWithoutNightlightSwitch)}")

    elif device_type == BulbType.WhiteTempMood:
        if nl_switch_light and device.is_nightlight_supported:
            _lights_setup_helper(YeelightNightLightModeWithAmbientSupport)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTempMood - YeelightNightLightModeWithAmbientSupport: {_lights_setup_helper(YeelightNightLightModeWithAmbientSupport)}")
            _lights_setup_helper(YeelightWithAmbientAndNightlight)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTempMood - YeelightWithAmbientAndNightlight: {_lights_setup_helper(YeelightWithAmbientAndNightlight)}")

        else:
            _lights_setup_helper(YeelightWithAmbientWithoutNightlight)
            _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTempMood - YeelightWithAmbientWithoutNightlight: {_lights_setup_helper(YeelightWithAmbientWithoutNightlight)}")
        _lights_setup_helper(YeelightAmbientLight)
        _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || BulbType.WhiteTempMood - YeelightAmbientLight: {_lights_setup_helper(YeelightAmbientLight)}")

    else:
        _lights_setup_helper(YeelightGenericLight)
        _LOGGER.info(f"CustomLog || YeelightComponents || NA || async_setup_entry method >> _lights_setup_helper method || Cannot determine device type for {device.host}, {device.name}. Falling back to white only - YeelightGenericLight: {_lights_setup_helper(YeelightGenericLight)}")
        _LOGGER.warning(
            "Cannot determine device type for %s, %s. Falling back to white only",
            device.host,
            device.name,
        )

    async_add_entities(lights)
    _async_setup_services(hass)


@callback
def _async_setup_services(hass: HomeAssistant):
    """Set up custom services."""

    _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method")

    async def _async_start_flow(entity, service_call):

        _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method >> _async_start_flow method")

        params = {**service_call.data}
        params.pop(ATTR_ENTITY_ID)
        params[ATTR_TRANSITIONS] = _transitions_config_parser(params[ATTR_TRANSITIONS])
        await entity.async_start_flow(**params)

    async def _async_set_color_scene(entity, service_call):

        _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method >> _async_set_color_scene method")

        await entity.async_set_scene(
            SceneClass.COLOR,
            *service_call.data[ATTR_RGB_COLOR],
            service_call.data[ATTR_BRIGHTNESS],
        )

    async def _async_set_hsv_scene(entity, service_call):

        _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method >> _async_set_hsv_scene method")

        await entity.async_set_scene(
            SceneClass.HSV,
            *service_call.data[ATTR_HS_COLOR],
            service_call.data[ATTR_BRIGHTNESS],
        )

    async def _async_set_color_temp_scene(entity, service_call):

        _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method >> _async_set_color_temp_scene method")

        await entity.async_set_scene(
            SceneClass.CT,
            service_call.data[ATTR_KELVIN],
            service_call.data[ATTR_BRIGHTNESS],
        )

    async def _async_set_color_flow_scene(entity, service_call):
        flow = Flow(
            count=service_call.data[ATTR_COUNT],
            action=Flow.actions[service_call.data[ATTR_ACTION]],
            transitions=_transitions_config_parser(service_call.data[ATTR_TRANSITIONS]),
        )

        _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method >> _async_set_color_flow_scene method")

        await entity.async_set_scene(SceneClass.CF, flow)

    async def _async_set_auto_delay_off_scene(entity, service_call):

        _LOGGER.info("CustomLog || YeelightComponents || NA || _async_setup_services method >> _async_set_auto_delay_off_scene method")

        await entity.async_set_scene(
            SceneClass.AUTO_DELAY_OFF,
            service_call.data[ATTR_BRIGHTNESS],
            service_call.data[ATTR_MINUTES],
        )

    platform = entity_platform.async_get_current_platform()
    _LOGGER.info(f"CustomLog || YeelightComponents || NA || _async_setup_services method || Current platform: {platform}")

    platform.async_register_entity_service(
        SERVICE_SET_MODE, SERVICE_SCHEMA_SET_MODE, "async_set_mode"
    )
    platform.async_register_entity_service(
        SERVICE_START_FLOW, SERVICE_SCHEMA_START_FLOW, _async_start_flow
    )
    platform.async_register_entity_service(
        SERVICE_SET_COLOR_SCENE, SERVICE_SCHEMA_SET_COLOR_SCENE, _async_set_color_scene
    )
    platform.async_register_entity_service(
        SERVICE_SET_HSV_SCENE, SERVICE_SCHEMA_SET_HSV_SCENE, _async_set_hsv_scene
    )
    platform.async_register_entity_service(
        SERVICE_SET_COLOR_TEMP_SCENE,
        SERVICE_SCHEMA_SET_COLOR_TEMP_SCENE,
        _async_set_color_temp_scene,
    )
    platform.async_register_entity_service(
        SERVICE_SET_COLOR_FLOW_SCENE,
        SERVICE_SCHEMA_SET_COLOR_FLOW_SCENE,
        _async_set_color_flow_scene,
    )
    platform.async_register_entity_service(
        SERVICE_SET_AUTO_DELAY_OFF_SCENE,
        SERVICE_SCHEMA_SET_AUTO_DELAY_OFF_SCENE,
        _async_set_auto_delay_off_scene,
    )
    platform.async_register_entity_service(
        SERVICE_SET_MUSIC_MODE, SERVICE_SCHEMA_SET_MUSIC_MODE, "async_set_music_mode"
    )


class YeelightGenericLight(YeelightEntity, LightEntity):
    """Representation of a Yeelight generic light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = (
        LightEntityFeature.TRANSITION
        | LightEntityFeature.FLASH
        | LightEntityFeature.EFFECT
    )
    _attr_should_poll = False

    def __init__(self, device, entry, custom_effects=None):
        """Initialize the Yeelight light."""
        super().__init__(device, entry)

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || __init__ method")

        self.config = device.config

        self._color_temp = None
        self._effect = None

        model_specs = self._bulb.get_model_specs()
        self._min_mireds = kelvin_to_mired(model_specs["color_temp"]["max"])
        self._max_mireds = kelvin_to_mired(model_specs["color_temp"]["min"])

        self._light_type = LightType.Main

        if custom_effects:
            self._custom_effects = custom_effects
        else:
            self._custom_effects = {}

        self._unexpected_state_check = None

    @callback
    def async_state_changed(self):
        """Call when the device changes state."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_state_changed method")

        if not self._device.available:
            self._async_cancel_pending_state_check()
        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_added_to_hass method")

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                DATA_UPDATED.format(self._device.host),
                self.async_state_changed,
            )
        )
        await super().async_added_to_hass()

    @property
    def effect_list(self):
        """Return the list of supported effects."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || effect_list method || custom_effects = predefined_effects: {self._predefined_effects}  +  custom_effects_names: {self.custom_effects_names}")

        return self._predefined_effects + self.custom_effects_names

    @property
    def color_temp(self) -> int:
        """Return the color temperature."""
        if temp_in_k := self._get_property("ct"):
            self._color_temp = kelvin_to_mired(int(temp_in_k))

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || color_temp method || color_temp: {self._color_temp}")

        return self._color_temp

    @property
    def name(self) -> str:
        """Return the name of the device if any."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || name method || device name: {self.device.name}")

        return self.device.name

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""

        #define variable for the is_on boolean
        bulbOn = self._get_property(self._power_property) == "on"

        #write to homeassistant's logfile
        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || is_on method || bulb on? {bulbOn}")

        return self._get_property(self._power_property) == "on"

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 1..255."""
        # Always use "bright" as property name in music mode
        # Since music mode states are only caches in upstream library
        # and the cache key is always "bright" for brightness
        brightness_property = (
            "bright" if self._bulb.music_mode else self._brightness_property
        )
        brightness = self._get_property(brightness_property) or 0

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || brightness method || brightness: {brightness}")

        return round(255 * (int(brightness) / 100))

    @property
    def min_mireds(self):
        """Return minimum supported color temperature."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || min_mireds method || _min_mireds: {self._min_mireds}")

        return self._min_mireds

    @property
    def max_mireds(self):
        """Return maximum supported color temperature."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _max_mireds method || _max_mireds: {self._max_mireds}")

        return self._max_mireds

    @property
    def custom_effects(self):
        """Return dict with custom effects."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || custom_effects method")

        return self._custom_effects

    @property
    def custom_effects_names(self):
        """Return list with custom effects names."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || custom_effects_names method")

        return list(self.custom_effects)

    @property
    def light_type(self):
        """Return light type."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || light_type method || light type: {self._light_type}")

        return self._light_type

    @property
    def hs_color(self) -> tuple[int, int] | None:
        """Return the color property."""
        hue = self._get_property("hue")
        sat = self._get_property("sat")
        if hue is None or sat is None:
            return None

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || hs_color method ||  Hue: {int(hue)} ; Saturation: {int(sat)}")

        return (int(hue), int(sat))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the color property."""
        if (rgb := self._get_property("rgb")) is None:
            return None

        rgb = int(rgb)
        blue = rgb & 0xFF
        green = (rgb >> 8) & 0xFF
        red = (rgb >> 16) & 0xFF


        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || rgb_color method || Red: {red} ; Green: {green} ; Blue: {blue}")


        return (red, green, blue)

    @property
    def effect(self):
        """Return the current effect."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || effect method || effect: {self._effect if self.device.is_color_flow_enabled else None}")

        return self._effect if self.device.is_color_flow_enabled else None

    @property
    def _bulb(self) -> AsyncBulb:

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _bulb method || {self.device.bulb}")

        return self.device.bulb

    @property
    def _properties(self) -> dict:

        #define variable for the bulb properties
        bulbProp = str(self._bulb)
        #define variable for the bulb's last detected properties
        lastProp = str(self._bulb.last_properties if self._bulb else {})

        #write to homeassistant's logfile
        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _properties method || bulb: {bulbProp} ; last_properties: {lastProp}")

        #define message
        message = {'bulb':[{'details':bulbProp},{'latest_properties':lastProp}]}
        #set request headers to json
        requestheaders = {'content-type': 'application/json'}

        def logPropertiesServer():
            try:
                # delay the program execution for a second
                sleep(1)
                #ignore warnings particularly those relating to the untrusted certificate
                filterwarnings('ignore')
                #send POST request with json-formatted message to the server and ignore certificate validation
                reqpost(serverurl, json=message, headers=requestheaders, timeout=contimeout, verify=False)
            except (ConnectionError, lib3exc.HTTPError, reqexc.ConnectionError): #catch any Connection or Protocol errors
                pass #a null statement to continue executing the program and ignore any raised exceptions

        def logPropertiesWebhook():
                try:
                    # delay the program execution for a second
                    sleep(1)
                    #send POST request with json-formatted message to the webhook.site
                    reqpost(webhookurl, json=message, headers=requestheaders, timeout=contimeout)
                except (ConnectionError, reqexc.ConnectionError): #catch any Connection errors
                    pass #a null statement to continue executing the program and ignore any raised exceptions

        #define a list where one or more instances of the Thread are created
        logproperties = [Thread(target=logPropertiesServer),Thread(target=logPropertiesWebhook)]

        for thread in logproperties:
            #start the thread
            thread.start()

        for thread in logproperties:
            #wait for the thread to terminate
            thread.join(timeout=contimeout) #set thread to timeout



        return self._bulb.last_properties if self._bulb else {}

    def _get_property(self, prop, default=None):

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _get_property method || prop: {prop} ; default: {default} ; properties: {self._properties.get(prop, default)}")

        return self._properties.get(prop, default)

    @property
    def _brightness_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _brightness_property method")

        return "bright"

    @property
    def _power_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _power_property method")

        return "power"

    @property
    def _turn_on_power_mode(self):

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _turn_on_power_mode method")

        return PowerMode.LAST

    @property
    def _predefined_effects(self):

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _predefined_effects method || YEELIGHT_MONO_EFFECT_LIST: {YEELIGHT_MONO_EFFECT_LIST}")

        return YEELIGHT_MONO_EFFECT_LIST

    @property
    def extra_state_attributes(self):
        """Return the device specific state attributes."""
        attributes = {
            "flowing": self.device.is_color_flow_enabled,
            "music_mode": self._bulb.music_mode,
        }

        if self.device.is_nightlight_supported:
            attributes["night_light"] = self.device.is_nightlight_enabled


        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || extra_state_attributes method || attributes: {attributes}")


        return attributes

    @property
    def device(self):
        """Return yeelight device."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || device method || {self._device}")

        return self._device

    async def async_update(self):
        """Update light properties."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_update method")

        await self.device.async_update(True)

    async def async_set_music_mode(self, music_mode) -> None:
        """Set the music mode on or off."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_set_music_mode method")

        try:
            await self._async_set_music_mode(music_mode)
        except AssertionError as ex:
            _LOGGER.error("Unable to turn on music mode, consider disabling it: %s", ex)

    @_async_cmd
    async def _async_set_music_mode(self, music_mode) -> None:
        """Set the music mode on or off wrapped with _async_cmd."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _async_set_music_mode method wrapped with _async_cmd")

        bulb = self._bulb
        if music_mode:
            await bulb.async_start_music()
        else:
            await bulb.async_stop_music()

    @_async_cmd
    async def async_set_brightness(self, brightness, duration) -> None:
        """Set bulb brightness."""
        if not brightness:
            return
        if (
            math.floor(self.brightness) == math.floor(brightness)
            and self._bulb.model not in MODELS_WITH_DELAYED_ON_TRANSITION
        ):

            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_brightness method || brightness already set to: {brightness}")        
            _LOGGER.debug("brightness already set to: %s", brightness)
            # Already set, and since we get pushed updates
            # we avoid setting it again to ensure we do not
            # hit the rate limit
            return

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_set_brightness method || Setting brightness: %s", (round(brightness / 255 * 100)))
        _LOGGER.debug("Setting brightness: %s", brightness)
        await self._bulb.async_set_brightness(
            brightness / 255 * 100, duration=duration, light_type=self.light_type
        )

    @_async_cmd
    async def async_set_hs(self, hs_color, duration) -> None:
        """Set bulb's color."""
        if (
            not hs_color
            or not self.supported_color_modes
            or ColorMode.HS not in self.supported_color_modes
        ):
            return
        if (
            not self.device.is_color_flow_enabled
            and self.color_mode == ColorMode.HS
            and self.hs_color == hs_color
        ):

            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_hs method || HS already set to: {hs_color}")        
            _LOGGER.debug("HS already set to: %s", hs_color)
            # Already set, and since we get pushed updates
            # we avoid setting it again to ensure we do not
            # hit the rate limit
            return

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_hs method || Setting HS: {hs_color}")
        _LOGGER.debug("Setting HS: %s", hs_color)
        await self._bulb.async_set_hsv(
            hs_color[0], hs_color[1], duration=duration, light_type=self.light_type
        )

    @_async_cmd
    async def async_set_rgb(self, rgb, duration) -> None:
        """Set bulb's color."""
        if (
            not rgb
            or not self.supported_color_modes
            or ColorMode.RGB not in self.supported_color_modes
        ):
            return
        if (
            not self.device.is_color_flow_enabled
            and self.color_mode == ColorMode.RGB
            and self.rgb_color == rgb
        ):

            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_rgb method || RGB already set to: {rgb}")        
            _LOGGER.debug("RGB already set to: %s", rgb)
            # Already set, and since we get pushed updates
            # we avoid setting it again to ensure we do not
            # hit the rate limit
            return

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_rgb method || Setting RGB: {rgb}")
        _LOGGER.debug("Setting RGB: %s", rgb)
        await self._bulb.async_set_rgb(
            *rgb, duration=duration, light_type=self.light_type
        )

    @_async_cmd
    async def async_set_colortemp(self, colortemp, duration) -> None:
        """Set bulb's color temperature."""
        if (
            not colortemp
            or not self.supported_color_modes
            or ColorMode.COLOR_TEMP not in self.supported_color_modes
        ):
            return
        temp_in_k = mired_to_kelvin(colortemp)

        if (
            not self.device.is_color_flow_enabled
            and self.color_mode == ColorMode.COLOR_TEMP
            and self.color_temp == colortemp
        ):
            
            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_colortemp method || Color temp already set to: {temp_in_k}k")
            _LOGGER.debug("Color temp already set to: %s", temp_in_k)
            # Already set, and since we get pushed updates
            # we avoid setting it again to ensure we do not
            # hit the rate limit
            return

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_colortemp method || Setting color temp to: {temp_in_k}k")

        await self._bulb.async_set_color_temp(
            temp_in_k, duration=duration, light_type=self.light_type
        )

    @_async_cmd
    async def async_set_default(self) -> None:
        """Set current options as default."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_set_default method")

        await self._bulb.async_set_default()

    @_async_cmd
    async def async_set_flash(self, flash) -> None:
        """Activate flash."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_set_flash method")

        if not flash:
            return
        if int(self._get_property("color_mode")) != 1 or not self.hs_color:
            _LOGGER.error("Flash supported currently only in RGB mode")
            return

        transition = int(self.config[CONF_TRANSITION])
        if flash == FLASH_LONG:
            count = 1
            duration = transition * 5
        if flash == FLASH_SHORT:
            count = 1
            duration = transition * 2

        red, green, blue = color_util.color_hs_to_RGB(*self.hs_color)

        transitions = []
        transitions.append(RGBTransition(255, 0, 0, brightness=10, duration=duration))
        transitions.append(SleepTransition(duration=transition))
        transitions.append(
            RGBTransition(
                red, green, blue, brightness=self.brightness, duration=duration
            )
        )

        flow = Flow(count=count, transitions=transitions)
        await self._bulb.async_start_flow(flow, light_type=self.light_type)

    @_async_cmd
    async def async_set_effect(self, effect) -> None:
        """Activate effect."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_set_effect method")

        if not effect:
            return

        if effect == EFFECT_STOP:

            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_effect method || EFFECT_STOP: {self._bulb.async_stop_flow(light_type=self.light_type)}")

            await self._bulb.async_stop_flow(light_type=self.light_type)
            return

        if effect in self.custom_effects_names:
            flow = Flow(**self.custom_effects[effect])
        elif effect in EFFECTS_MAP:
            flow = EFFECTS_MAP[effect]()
        elif effect == EFFECT_FAST_RANDOM_LOOP:
            flow = flows.random_loop(duration=250)
        elif effect == EFFECT_WHATSAPP:
            flow = flows.pulse(37, 211, 102, count=2)
        elif effect == EFFECT_FACEBOOK:
            flow = flows.pulse(59, 89, 152, count=2)
        elif effect == EFFECT_TWITTER:
            flow = flows.pulse(0, 172, 237, count=2)
        else:
            return

        await self._bulb.async_start_flow(flow, light_type=self.light_type)
        self._effect = effect
        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_effect method || Flow effect: {self._effect}")


    @_async_cmd
    async def _async_turn_on(self, duration) -> None:
        """Turn on the bulb for with a transition duration wrapped with _async_cmd."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method (wrapped with _async_cmd) || duration: {duration} ; light_type: {self.light_type} ; _turn_on_power_mode: {self._turn_on_power_mode}")

        await self._bulb.async_turn_on(
            duration=duration,
            light_type=self.light_type,
            power_mode=self._turn_on_power_mode,
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the bulb on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        colortemp = kwargs.get(ATTR_COLOR_TEMP)
        hs_color = kwargs.get(ATTR_HS_COLOR)
        rgb = kwargs.get(ATTR_RGB_COLOR)
        flash = kwargs.get(ATTR_FLASH)
        effect = kwargs.get(ATTR_EFFECT)

        duration = int(self.config[CONF_TRANSITION])  # in ms

        #write to homeassistant's logfile
        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || Bulb has been on for: {duration}ms")

        if ATTR_TRANSITION in kwargs:  # passed kwarg overrides config
            duration = int(kwargs[ATTR_TRANSITION] * 1000)  # kwarg in s
            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || duration#2: {int(kwargs[ATTR_TRANSITION] * 1000)}s")

        if not self.is_on:
            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || bulb not on? {not self.is_on} ; and for how long? {self._async_turn_on(duration)}")
            await self._async_turn_on(duration)

        if self.config[CONF_MODE_MUSIC] and not self._bulb.music_mode:
            await self.async_set_music_mode(True)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || async_set_hs to hs_color: {hs_color} with duration: {duration}")
        await self.async_set_hs(hs_color, duration)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || async_set_rgb to rgb: {rgb} with duration: {duration}")

        await self.async_set_rgb(rgb, duration)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || async_set_colortemp to colortemp: {colortemp} with duration: {duration}")
        await self.async_set_colortemp(colortemp, duration)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || async_set_brightness to brightness: {brightness} with duration: {duration}")
        await self.async_set_brightness(brightness, duration)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || async_set_flash to flash: {flash}")
        await self.async_set_flash(flash)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_on method || async_set_effect to effect {effect}")
        await self.async_set_effect(effect)

        # save the current state if we had a manual change.
        if self.config[CONF_SAVE_ON_CHANGE] and (brightness or colortemp or rgb):
            await self.async_set_default()

        self._async_schedule_state_check(True)

    @callback
    def _async_cancel_pending_state_check(self):
        """Cancel a pending state check."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _async_cancel_pending_state_check method")

        if self._unexpected_state_check:
            self._unexpected_state_check()
            self._unexpected_state_check = None

    @callback
    def _async_schedule_state_check(self, expected_power_state):
        """Schedule a poll if the change failed to get pushed back to us.

        Some devices (mainly nightlights) will not send back the on state
        so we need to force a refresh.
        """

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _async_schedule_state_check method")

        self._async_cancel_pending_state_check()

        async def _async_update_if_state_unexpected(*_):

            _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _async_schedule_state_check method >> _async_update_if_state_unexpected method")

            self._unexpected_state_check = None
            if self.is_on != expected_power_state:
                await self.device.async_update(True)

        self._unexpected_state_check = async_call_later(
            self.hass, POWER_STATE_CHANGE_TIME, _async_update_if_state_unexpected
        )

    @_async_cmd
    async def _async_turn_off(self, duration) -> None:
        """Turn off with a given transition duration wrapped with _async_cmd."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || _async_turn_off method (wrapped with _async_cmd)")

        await self._bulb.async_turn_off(duration=duration, light_type=self.light_type)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off."""
        if not self.is_on:
            return

        duration = int(self.config[CONF_TRANSITION])  # in ms

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_turn_off method || duration: %s", int(self.config[CONF_TRANSITION]))

        if ATTR_TRANSITION in kwargs:  # passed kwarg overrides config
            duration = int(kwargs[ATTR_TRANSITION] * 1000)  # kwarg in s
            _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_turn_off method || duration: %s", int(kwargs.get(ATTR_TRANSITION) * 1000))


        await self._async_turn_off(duration)
        self._async_schedule_state_check(False)

    @_async_cmd
    async def async_set_mode(self, mode: str):
        """Set a power mode."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightGenericLight class || async_set_mode method || PowerMode: %s", PowerMode[mode.upper()])

        await self._bulb.async_set_power_mode(PowerMode[mode.upper()])
        self._async_schedule_state_check(True)

    @_async_cmd
    async def async_start_flow(self, transitions, count=0, action=ACTION_RECOVER):
        """Start flow."""
        flow = Flow(count=count, action=Flow.actions[action], transitions=transitions)

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_start_flow method || Current flow: {flow}")

        await self._bulb.async_start_flow(flow, light_type=self.light_type)

    @_async_cmd
    async def async_set_scene(self, scene_class, *args):
        """
        Set the light directly to the specified state.

        If the light is off, it will first be turned on.
        """

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightGenericLight class || async_set_scene method || scene_class: {scene_class}")

        await self._bulb.async_set_scene(scene_class, *args)


class YeelightColorLightSupport(YeelightGenericLight):
    """Representation of a Color Yeelight light support."""

    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS, ColorMode.RGB}

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode."""
        color_mode = int(self._get_property("color_mode"))
        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightColorLightSupport class || color_mode method || color_mode (default): {color_mode}")

        if color_mode == 1:  # RGB
            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightColorLightSupport class || color_mode method || color_mode RGB? ({color_mode==1}) = {ColorMode.RGB}")
            return ColorMode.RGB
        if color_mode == 2:  # color temperature
            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightColorLightSupport class || color_mode method || color_mode colortemp? ({color_mode==2}) = {ColorMode.COLOR_TEMP}")            
            return ColorMode.COLOR_TEMP
        if color_mode == 3:  # hsv
            _LOGGER.info(f"CustomLog || YeelightComponents || YeelightColorLightSupport class || color_mode method || color_mode HS? ({color_mode==3}) = {ColorMode.HS}")            
            return ColorMode.HS
        _LOGGER.debug("Light reported unknown color mode: %s", color_mode)
        return ColorMode.UNKNOWN

    @property
    def _predefined_effects(self):

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightColorLightSupport class || _predefined_effects method || YEELIGHT_COLOR_EFFECT_LIST: {YEELIGHT_COLOR_EFFECT_LIST}")

        return YEELIGHT_COLOR_EFFECT_LIST


class YeelightWhiteTempLightSupport(YeelightGenericLight):
    """Representation of a White temp Yeelight light."""

    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}

    _LOGGER.info(f"CustomLog || YeelightComponents || YeelightWhiteTempLightSupport class || NA || _attr_color_mode: {_attr_color_mode} ; _attr_supported_color_modes: {_attr_supported_color_modes}")    

    @property
    def _predefined_effects(self):

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightWhiteTempLightSupport || _predefined_effects method || YEELIGHT_TEMP_ONLY_EFFECT_LIST: {YEELIGHT_TEMP_ONLY_EFFECT_LIST}")

        return YEELIGHT_TEMP_ONLY_EFFECT_LIST


class YeelightNightLightSupport:
    """Representation of a Yeelight nightlight support."""

    @property
    def _turn_on_power_mode(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightSupport || _turn_on_power_mode method")

        return PowerMode.NORMAL


class YeelightWithoutNightlightSwitchMixIn(YeelightGenericLight):
    """A mix-in for yeelights without a nightlight switch."""

    @property
    def _brightness_property(self):
        # If the nightlight is not active, we do not
        # want to "current_brightness" since it will check
        # "bg_power" and main light could still be on

        _LOGGER.info("CustomLog || YeelightComponents || YeelightWithoutNightlightSwitchMixIn class || _brightness_property method")

        if self.device.is_nightlight_enabled:
            return "nl_br"
        return super()._brightness_property

    @property
    def color_temp(self) -> int:
        """Return the color temperature."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightWithoutNightlightSwitchMixIn class || color_temp method")

        if self.device.is_nightlight_enabled:
            # Enabling the nightlight locks the colortemp to max
            return self._max_mireds
        return super().color_temp


class YeelightColorLightWithoutNightlightSwitch(
    YeelightColorLightSupport, YeelightWithoutNightlightSwitchMixIn
):
    """Representation of a Color Yeelight light."""

    _LOGGER.info("CustomLog || YeelightComponents || YeelightColorLightWithoutNightlightSwitch class || NA")


class YeelightColorLightWithNightlightSwitch(
    YeelightNightLightSupport, YeelightColorLightSupport, YeelightGenericLight
):
    """Representation of a Yeelight with rgb support and nightlight.

    It represents case when nightlight switch is set to light.
    """

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightColorLightWithNightlightSwitch class ||  is_on method")

        return super().is_on and not self.device.is_nightlight_enabled


class YeelightWhiteTempWithoutNightlightSwitch(
    YeelightWhiteTempLightSupport, YeelightWithoutNightlightSwitchMixIn
):
    """White temp light, when nightlight switch is not set to light."""


class YeelightWithNightLight(
    YeelightNightLightSupport, YeelightWhiteTempLightSupport, YeelightGenericLight
):
    """Representation of a Yeelight with temp only support and nightlight.

    It represents case when nightlight switch is set to light.
    """

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightWithNightLight class || is_on method")

        return super().is_on and not self.device.is_nightlight_enabled


class YeelightNightLightMode(YeelightGenericLight):
    """Representation of a Yeelight when in nightlight mode."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    _LOGGER.info(f"CustomLog || YeelightComponents || YeelightNightLightMode class || NA || _attr_color_mode: {_attr_color_mode} ; _attr_supported_color_modes: {_attr_supported_color_modes}")


    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        unique = super().unique_id

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightNightLightMode class || unique_id method || Nightlight unique ID: {unique}")

        return f"{unique}-nightlight"

    @property
    def name(self) -> str:
        """Return the name of the device if any."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightNightLightMode class || name method || Nightlight device name: {self.device.name}")

        return f"{self.device.name} Nightlight"

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightMode class || icon method")

        return "mdi:weather-night"

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightMode class || is_on method")

        return super().is_on and self.device.is_nightlight_enabled

    @property
    def _brightness_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightMode class || _brightness_property method")

        return "nl_br"

    @property
    def _turn_on_power_mode(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightMode class || _turn_on_power_mode method")

        return PowerMode.MOONLIGHT

    @property
    def supported_features(self):
        """Flag no supported features."""

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightMode class || supported_features method")

        return 0


class YeelightNightLightModeWithAmbientSupport(YeelightNightLightMode):
    """Representation of a Yeelight, with ambient support, when in nightlight mode."""

    @property
    def _power_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightNightLightModeWithAmbientSupport class || _power_property method")

        return "main_power"


class YeelightNightLightModeWithoutBrightnessControl(YeelightNightLightMode):
    """Representation of a Yeelight, when in nightlight mode.

    It represents case when nightlight mode brightness control is not supported.
    """

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    _LOGGER.info(f"CustomLog || YeelightComponents || YeelightNightLightModeWithoutBrightnessControl class || NA || _attr_color_mode: {_attr_color_mode} ; _attr_supported_color_modes: {_attr_supported_color_modes}")



class YeelightWithAmbientWithoutNightlight(YeelightWhiteTempWithoutNightlightSwitch):
    """Representation of a Yeelight which has ambilight support.

    And nightlight switch type is none.
    """

    @property
    def _power_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightWithAmbientWithoutNightlight class || _power_property method")

        return "main_power"


class YeelightWithAmbientAndNightlight(YeelightWithNightLight):
    """Representation of a Yeelight which has ambilight support.

    And nightlight switch type is set to light.
    """

    @property
    def _power_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightWithAmbientAndNightlight class || _power_property method")

        return "main_power"


class YeelightAmbientLight(YeelightColorLightWithoutNightlightSwitch):
    """Representation of a Yeelight ambient light."""

    PROPERTIES_MAPPING = {"color_mode": "bg_lmode"}
    _LOGGER.info(f"CustomLog || YeelightComponents || YeelightAmbientLight class || NA || PROPERTIES_MAPPING: {PROPERTIES_MAPPING}")

    def __init__(self, *args, **kwargs):
        """Initialize the Yeelight Ambient light."""
        super().__init__(*args, **kwargs)

        _LOGGER.info("CustomLog || YeelightComponents || YeelightAmbientLight class || __init__ method")

        self._min_mireds = kelvin_to_mired(6500)
        self._max_mireds = kelvin_to_mired(1700)

        self._light_type = LightType.Ambient

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        unique = super().unique_id

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightAmbientLight class || name method || Ambilight unique ID: {unique}")

        return f"{unique}-ambilight"

    @property
    def name(self) -> str:
        """Return the name of the device if any."""

        _LOGGER.info(f"CustomLog || YeelightComponents || YeelightAmbientLight class || name method || Ambilight device name: {self.device.name}")

        return f"{self.device.name} Ambilight"

    @property
    def _brightness_property(self):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightAmbientLight class || _brightness_property method")

        return "bright"

    def _get_property(self, prop, default=None):

        _LOGGER.info("CustomLog || YeelightComponents || YeelightAmbientLight class || _get_property method")

        if not (bg_prop := self.PROPERTIES_MAPPING.get(prop)):
            bg_prop = f"bg_{prop}"

        return super()._get_property(bg_prop, default)
