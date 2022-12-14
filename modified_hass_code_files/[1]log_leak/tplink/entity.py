"""Common code for tplink."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

from kasa import SmartDevice
from typing_extensions import Concatenate, ParamSpec

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TPLinkDataUpdateCoordinator

import logging


_T = TypeVar("_T", bound="CoordinatedTPLinkEntity")
_P = ParamSpec("_P")

_LOGGER = logging.getLogger(__name__)

def async_refresh_after(
    func: Callable[Concatenate[_T, _P], Awaitable[None]]
) -> Callable[Concatenate[_T, _P], Coroutine[Any, Any, None]]:
    """Define a wrapper to refresh after."""

    _LOGGER.info("CustomLog || TPLink || NA || async_refresh_after method")

    async def _async_wrap(self: _T, *args: _P.args, **kwargs: _P.kwargs) -> None:

        _LOGGER.info("CustomLog || TPLink || NA || async_refresh_after method >> _async_wrap method")

        await func(self, *args, **kwargs)
        await self.coordinator.async_request_refresh_without_children()

    return _async_wrap


class CoordinatedTPLinkEntity(CoordinatorEntity[TPLinkDataUpdateCoordinator]):
    """Common base class for all coordinated tplink entities."""

    def __init__(
        self, device: SmartDevice, coordinator: TPLinkDataUpdateCoordinator
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.device: SmartDevice = device
        self._attr_name = self.device.alias
        self._attr_unique_id = self.device.device_id

        _LOGGER.info(f"CustomLog || TPLink || CoordinatedTPLinkEntity class || __init__ method || device: {device} ; name (alias): {self.device.alias} ; device unique_id: {self.device.device_id}")


    @property
    def device_info(self) -> DeviceInfo:
        """Return information about the device."""

        _LOGGER.info(f"CustomLog || TPLink || CoordinatedTPLinkEntity class || device_info method || connections - device mac: {self.device.mac} ; identifiers - DOMAIN: {DOMAIN} // device_id: {str(self.device.device_id)} ; model: {self.device.model} ; manufacturer: TP-Link ; name (alias): {self.device.alias} ; sw_version: {self.device.hw_info['sw_ver']} ; hw_version: {self.device.hw_info['hw_ver']}")

        return DeviceInfo(
            connections={(dr.CONNECTION_NETWORK_MAC, self.device.mac)},
            identifiers={(DOMAIN, str(self.device.device_id))},
            manufacturer="TP-Link",
            model=self.device.model,
            name=self.device.alias,
            sw_version=self.device.hw_info["sw_ver"],
            hw_version=self.device.hw_info["hw_ver"],
        )

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""

        switchOn = bool(self.device.is_on)

        #write to homeassistant's logfile
        _LOGGER.info(f"CustomLog || TPLink || CoordinatedTPLinkEntity class || is_on method || is the switch on? {switchOn}")     

        return bool(self.device.is_on)
