"""
Loxone cover component.
"""
import logging
import collections
from typing import Any
from voluptuous import All, Range, Optional

from homeassistant.components.climate.const import (
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_AWAY,
     HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,    
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_AUTO,
)

from homeassistant.components.climate import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    TEMP_CELSIUS,
    ATTR_HVAC_MODE,
    ClimateEntity,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
    PLATFORM_SCHEMA
)

from homeassistant.const import (
    CONF_VALUE_TEMPLATE, CONF_NAME)
from homeassistant.helpers.event import track_utc_time_change

from . import LoxoneEntity
from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid, get_all_roomcontroller_entities

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'loxone'
EVENT = "loxone_event"
SENDDOMAIN = "loxone_send"

CONF_HVAC_AUTO_MODE = 'hvac_auto_mode'

OPMODES = {
        None: HVAC_MODE_OFF,
        0: HVAC_MODE_AUTO,
        1: HVAC_MODE_AUTO,
        2: HVAC_MODE_AUTO,
        3: HVAC_MODE_HEAT_COOL,
        4: HVAC_MODE_HEAT,
        5: HVAC_MODE_COOL }

OPMODETOLOXONE = {
    HVAC_MODE_HEAT_COOL: 3,
    HVAC_MODE_HEAT: 4,
    HVAC_MODE_COOL: 5
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
        Optional(CONF_HVAC_AUTO_MODE, default=0):
            All(int, Range(min=0, max=2)),
    })

#SUPPORT_SET_TEMP = 4
#SUPPORT_AUX_HEAT = 8
#SUPPORT_FAN_MODE = 16
#SUPPORT_PRESET_MODE = 32
#SUPPORT_SWING_MODE = 64
#SUPPORT_TARGET_HUMIDITY = 128
#SUPPORT_TARGET_TEMPERATURE = 256
#SUPPORT_TARGET_TEMPERATURE_RANGE = 512
#other support values 8, 16...

async def async_setup_platform(hass, config, async_add_devices, discovery_info={}):
    value_template = config.get(CONF_VALUE_TEMPLATE)
    name = config.get(CONF_NAME)
    autoMode = 0 if config.get(CONF_HVAC_AUTO_MODE) is None else config.get(CONF_HVAC_AUTO_MODE)

    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']

    devices = []

    for climate in get_all_roomcontroller_entities(loxconfig):
        climate.update({'hass': hass,
                      'room': get_room_name_from_room_uuid(loxconfig, climate.get('room', '')),
                      'cat': get_cat_name_from_cat_uuid(loxconfig, climate.get('cat', '')),
                      'autoMode': autoMode})

        new_thermostat = LoxoneRoomController(**climate)
        devices.append(new_thermostat)
        hass.bus.async_listen(EVENT, new_thermostat.event_handler)
        
    async_add_devices(devices)
    return True

class LoxoneRoomController(LoxoneEntity, ClimateEntity):
    
    """Loxone room controller"""

    def __init__(self, **kwargs):
        _LOGGER.debug(f"Input: {kwargs}")
        LoxoneEntity.__init__(self, **kwargs)
        self.hass = kwargs['hass']
        self.autoMode = kwargs['autoMode']

        self._stateAttribUuids = kwargs['states']
        self._stateAttribValues = {}
        
        self._modeList = []
        for mode in kwargs['details']['timerModes']:
             self._modeList.append(mode)

    def getModeFromId(self, modeId):
        for mode in self._modeList:
            if mode['id'] == modeId:
                return mode['name']

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_PRESET_MODE | SUPPORT_TARGET_TEMPERATURE

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    async def event_handler(self, event):
        _LOGGER.debug(f"Climate Event data: {event.data}")
        update = False

        for key in (set(self._stateAttribUuids.values()) & event.data.keys()):
            self._stateAttribValues[key] = event.data[key]
            update = True
     
        if update:
            self.schedule_update_ha_state()

        _LOGGER.debug(f"State attribs after event handling: {self._stateAttribValues}")


    def getStateValue(self, name):
        uuid = self._stateAttribUuids[name]
        return self._stateAttribValues[uuid] if uuid in self._stateAttribValues else None


    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "device_typ": self.type,
                "room": self.room, "category": self.cat,
                "plattform": "loxone"}

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.getStateValue("tempActual")

    def set_temperature(self, **kwargs):
        """Set new target temperature"""
        if (self.getStateValue("operatingMode") > 2): #Set manual temp if any of the manual modes selected
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=f'setManualTemperature/{kwargs["temperature"]}'))    
        else: #Set comfort temp offset otherwise
            newOffset = kwargs["temperature"] - self.getStateValue("comfortTemperature")
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=f'setComfortModeTemp/{newOffset}'))

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        return OPMODES[self.getStateValue("operatingMode")]

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return [HVAC_MODE_AUTO, HVAC_MODE_HEAT, HVAC_MODE_HEAT_COOL, HVAC_MODE_COOL]

    @property
    def temperature_unit(self):
        """Return the unit of measurement used by the platform."""
        
        return TEMP_CELSIUS

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        
        return self.getStateValue("tempTarget")

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp.

        Requires SUPPORT_PRESET_MODE.
        """
        #return self._activeMode
        return self.getModeFromId(self.getStateValue("activeMode"))

    @property
    def preset_modes(self):
        """Return a list of available preset modes.

        Requires SUPPORT_PRESET_MODE.
        """
        return [mode['name'] for mode in self._modeList]

    def set_hvac_mode(self, hvac_mode: str):
        """Set new target hvac mode."""

        targetMode = self.autoMode if hvac_mode == HVAC_MODE_AUTO else OPMODETOLOXONE[hvac_mode]
        
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=f'setOperatingMode/{targetMode}'))

        self.schedule_update_ha_state()

        #if the mode selected is a manual one, we set the target temperature too
        #if (hvac_mode != HVAC_MODE_AUTO):
        #    self.set_temperature({"temperature": self.target_temperature})

    def set_preset_mode(self, preset_mode: str):
        """Set new preset mode."""
        modeId = next((mode["id"] for mode in self._modeList if mode['name'] == preset_mode), None)
        if (modeId is not None):
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=f'override/{modeId}'))
            self.schedule_update_ha_state()
