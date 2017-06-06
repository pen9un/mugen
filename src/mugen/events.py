import copy
from enum import Enum
from fractions import Fraction
from typing import List, Optional as Opt, Union
from itertools import groupby, zip_longest
from operator import attrgetter

import mugen.utility as util
import mugen.location_utility as loc_util
from mugen import lists
from mugen.constants import TIME_FORMAT
from mugen.lists import MugenList
from mugen.utility import convert_float_to_fraction, convert_time_to_seconds


class EventType(str, Enum):
    """
    Type of an event
    """
    pass


class EventsMode(str, Enum):
    """
    Method of generating events
    """
    pass


class Event:
    """
    An event which occurs in some time sequence (i.e a song, or music video)

    Attributes
    ----------    
    location
        location of the event in the time sequence (seconds)
        
    duration
        duration of the event (seconds)
        
    type
        type of the event
    """
    location: float
    duration: float
    type: str

    @convert_time_to_seconds(['location', 'duration'])
    def __init__(self, location: TIME_FORMAT, *, duration: TIME_FORMAT = 0, type: str = 'unknown'):
        self.location = location
        self.duration = duration
        self.type = type

    def __repr__(self):
        return self.index_repr()

    def index_repr(self, index: Opt[int] = None):
        if index is None:
            repr_str = f"<Event, "
        else:
            repr_str = f"<Event {index}, "
        repr_str += f"location: {self.location:.3f}, "
        if self.duration:
            repr_str += f"duration:{self.duration:.3f}, "
        repr_str += f"type: {self.type}>"

        return repr_str

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self == other


class EventList(MugenList):
    """
    A list of Events with extended functionality
    """
    type: str

    def __init__(self, events: Opt[Union[List[Event], List[TIME_FORMAT]]] = None):
        if events is None:
            events = []
        elif events and type(events[0]) != Event:
            # Convert inputs to Events
            events = [Event(event) for event in events]

        super().__init__(events)

    # def __repr__(self):
    #     event_list_str = ""
    #     for index, event in enumerate(self):
    #         event_list_str += event.index_repr(index)
    #
    #         if index != len(self) - 1:
    #             event_list_str += ', '
    #     return f'[{event_list_str}]'

    @property
    def alt_repr(self):
        """
        Alternate representation
        """
        return f'<EventList ({len(self)}), type: {self.type}>'

    @property
    def type(self) -> Union[str, None]:
        if len(self) == 0:
            return None
        elif len(set([event.type for event in self])) == 1:
            return self[0].type
        else:
            return 'mixed'

    @property
    def locations(self) -> List[float]:
        return [event.location for event in self]

    @property
    def intervals(self) -> List[float]:
        return loc_util.intervals_from_locations(self.locations)

    @property
    def durations(self) -> List[float]:
        return [event.duration for event in self]

    @property
    def types(self) -> List[str]:
        return [event.type for event in self]

    def offset(self, offset: float):
        """
        Offsets all events by the given amount         
        """
        for event in self:
            event.location += offset

    @convert_float_to_fraction('speed')
    def speed_multiply(self, speed: Union[float, Fraction],
                       offset: Opt[int] = None):
        """
        Speeds up or slows down events by grouping them together or splitting them up.
        For slowdowns, event type group boundaries and isolated events are preserved.

        Parameters
        ----------
        speed
            Factor to speedup or slowdown by. 
            Must be of the form x (speedup) or 1/x (slowdown), where x is a natural number.
            Otherwise, 0 to remove all events.
            
        offset
            Offsets the grouping of events for slowdowns.
            Takes a max offset of x - 1 for a slowdown of 1/x, where x is a natural number
        """
        if speed == 0:
            self.clear()
        elif speed > 1:
            self._split(speed.numerator)
        elif speed < 1:
            self._merge(speed.denominator, offset)

    def _split(self, pieces_per_split: int):
        """
        Splits events up to form shorter intervals

        Parameters
        ----------
        pieces_per_split
            Number of pieces to split each event into
        """
        splintered_events = EventList()

        # Group events by type
        type_groups = self.group_by_type()

        for group in type_groups:
            if len(group) == 1:
                # Always keep isolated events
                splintered_events.append(group[0])
            else:
                for index, event in enumerate(group):
                    splintered_events.append(event)

                    if index == len(group) - 1:
                        # Skip last event
                        continue

                    next_event = group[index + 1]
                    interval = next_event.location - event.location
                    interval_piece = interval / pieces_per_split

                    location = event.location
                    for _ in range(pieces_per_split - 1):
                        location += interval_piece
                        event_splinter = copy.deepcopy(event)
                        event_splinter.location = location
                        splintered_events.append(event_splinter)

        self[:] = splintered_events

    def _merge(self, pieces_per_merge: int, offset: Opt[int] = None):
        """
        Merges adjacent events of identical type to form longer intervals

        Parameters
        ----------
        pieces_per_merge 
            Number of adjacent events to merge at a time
            
        offset
            Offset for the merging of events
        """
        if offset is None:
            offset = 0

        combined_events = EventList()

        # Group events by type
        type_groups = self.group_by_type()
        for group in type_groups:
            if len(group) == 1:
                # Always keep isolated events
                combined_events.append(group[0])
            else:
                for index, event in enumerate(group):
                    if (index - offset) % pieces_per_merge == 0:
                        combined_events.append(event)

        self[:] = combined_events

    def group_by_type(self, primaries: List[str] = None) -> 'EventGroupList':
        """
        Groups events by type

        Attributes
        ----------
        primaries
            A list of types corresponding to primary groups in the resulting EventGroupList.
        
        Returns
        -------
        An EventGroupList
        """
        if primaries is None:
            primaries = []

        groups = [EventList(list(group)) for index, group in groupby(self, key=attrgetter('type'))]
        primary_groups = [group for group in groups if group.type in primaries]

        return EventGroupList(groups, primaries=primary_groups)

    def group_by_slices(self, slices: (int, int)) -> 'EventGroupList':
        """
        Groups events by slices.
        Does not support negative indexing.

        Slices explicitly passed in will become primary groups in the resulting EventGroupList.

        Returns
        -------
        An EventGroupList
        """
        slices = [slice(sl[0], sl[1]) for sl in slices]

        # Fill in rest of slices
        all_slices = util.fill_slices(slices, len(self))
        target_indexes = [index for index, sl in enumerate(all_slices) if sl in slices]

        # Group events by slices
        groups = [self[sl] for sl in all_slices]
        primaries = [group for index, group in enumerate(groups) if index in target_indexes]
        groups = EventGroupList(groups, primaries=primaries)

        return groups


class EventGroupList(MugenList):
    """
    An alternate, more useful representation for a list of EventLists

    Attributes
    ----------
    _primary_groups
        The primary list of groups to track
    """
    _primary_groups: List[EventList]

    def __init__(self, groups: Opt[Union[List[EventList], List[List[TIME_FORMAT]]]] = None, *,
                 primaries: List[EventList] = None):
        """
        Parameters
        ----------
        groups

        primaries
            The primary list of groups to track
        """
        if groups is None:
            groups = []
        elif groups and type(groups[0]) != EventList:
            # Convert inputs to EventLists
            groups = [EventList(group) for group in groups]

        super().__init__(groups)

        self._primary_groups = primaries if primaries is not None else []

    def __repr__(self):
        event_groups_str = ""
        for index, l in enumerate(self):
            event_groups_str += l.alt_repr

            if index != len(self) - 1:
                event_groups_str += ', '
        return f'[{event_groups_str}]'

    @property
    def primary_groups(self) -> 'EventGroupList':
        """
        Returns
        -------
        Primary groups
        """
        return EventGroupList([group for group in self._primary_groups])

    @property
    def secondary_groups(self) -> 'EventGroupList':
        """
        Returns
        -------
        Non-primary groups
        """
        return EventGroupList([group for group in self if group not in self.primary_groups])

    def speed_multiply(self, speeds: List[float], offsets: Opt[List[float]] = None):
        """
        Speed multiplies event groups, in order

        See :meth:`~mugen.events.EventList.speed_multiply` for further information.
        """
        if offsets is None:
            offsets = []

        for group, speed, offset in zip_longest(self, speeds, offsets):
            group.speed_multiply(speed if speed is not None else 1, offset)

    def flatten(self) -> EventList:
        """
        Flattens the EventGroupList back into an EventList.
        Supports an arbitrary level of nesting.

        Returns
        -------
        A flattened EventList for this EventGroupList
        """
        return EventList(lists.flatten(self))