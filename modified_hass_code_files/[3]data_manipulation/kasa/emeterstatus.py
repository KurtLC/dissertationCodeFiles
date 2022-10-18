"""Module for emeter container."""
import logging
from typing import Optional


_LOGGER = logging.getLogger(__name__)


class EmeterStatus(dict):
    """Container for converting different representations of emeter data.

    Newer FW/HW versions postfix the variable names with the used units,
    where-as the olders do not have this feature.

    This class automatically converts between these two to allow
    backwards and forwards compatibility.
    """

    @property
    def voltage(self) -> Optional[float]:
        """Return voltage in V."""

        try:
            _LOGGER.info("CustomLog || Kasa || EmeterStatus class || voltage method || Voltage: %sV", self["voltage"])
            return self["voltage"]
        except ValueError:
            return None

    @property
    def power(self) -> Optional[float]:
        """Return power in W."""
        try:
            #define variable for power and round up to 2 decimal places
            emeterPower = round(self["power"],2)

            _LOGGER.info(f"CustomLog || Kasa || EmeterStatus class || power method || Actual power value: {emeterPower}W \\\\ Manipulated power value: {(self['power']-self['power'])}W")

            return (self["power"]-self["power"]) #modified from: return self["power"]
        except ValueError:
            return None

    @property
    def current(self) -> Optional[float]:
        """Return current in A."""

        try:
            _LOGGER.info("CustomLog || Kasa || EmeterStatus class || current method || Current: %sA", self["current"])
            return self["current"]
        except ValueError:
            return None

    @property
    def total(self) -> Optional[float]:
        """Return total in kWh."""
        try:
            _LOGGER.info("CustomLog || Kasa || EmeterStatus class || total method || Total consumption: %skWh", self["total"])
            return self["total"]
        except ValueError:
            return None

    def __repr__(self):


        _LOGGER.info(f"CustomLog || Kasa || EmeterStatus class || __repr__ method || power:{self.power}W ; voltage:{self.voltage}V ; current:{self.current}A ; total:{self.total}kWh")

        return f"<EmeterStatus power={self.power} voltage={self.voltage} current={self.current} total={self.total}>"

    def __getitem__(self, item):
        valid_keys = [
            "voltage_mv",
            "power_mw",
            "current_ma",
            "energy_wh",
            "total_wh",
            "voltage",
            "power",
            "current",
            "total",
            "energy",
        ]


        # 1. if requested data is available, return it
        if item in super().keys():
            # _LOGGER.info(f"CustomLog || Kasa || EmeterStatus class || __getitem__ method || item: {item}")
            return super().__getitem__(item)

        # otherwise decide how to convert it
        else:
            if item not in valid_keys:
                raise KeyError(item)
            if "_" in item:  # upscale
                return super().__getitem__(item[: item.find("_")]) * 1000
            else:  # downscale
                for i in super().keys():
                    if i.startswith(item):
                        return self.__getitem__(i) / 1000

                _LOGGER.debug(f"Unable to find value for '{item}'")
                return None
