import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import { Checkbox, CheckboxGroup, DateTimePicker } from './Controls.js';

function DebugOptions({ debug, currentTime, setCurrentTime }) {
  if (!debug) { return null; }

  return (
    <>
      <h3>Debug Nonsense</h3>
      <p>
        <label>Current time:</label>
        <DateTimePicker value={currentTime} onChange={setCurrentTime} />
      </p>
    </>
  );
}

function Filters({ schedule, onlyFavourites, setOnlyFavourites, selectedVenues, setSelectedVenues, selectedEventTypes, setSelectedEventTypes, debug, currentTime, setCurrentTime }) {
  const [visible, setVisible] = useState(false);

  function selectOfficialVenues(ev) {
    ev.preventDefault();
    setSelectedVenues(schedule.venues.filter(v => v.official).map(v => v.name));
  }

  function renderDebugOptions() {
  }

  function renderBody() {
    let venueFilters = [
      { name: 'Official Venues Only', callback: selectOfficialVenues }
    ];

    return (
      <div className="panel-body">
        <h3>Favourites</h3>
        <div className="form-group form-inline">
          <Checkbox checked={ onlyFavourites } onChange={ setOnlyFavourites }>
            Favourites only
          </Checkbox>
        </div>

        <h3>Venues</h3>
        <CheckboxGroup
          options={ schedule.venues.map(v => v.name) }
          selectedOptions={ selectedVenues }
          onChange={ setSelectedVenues }
          filters={ venueFilters } />

        <h3>Event Types</h3>
        <CheckboxGroup
          options={ schedule.eventTypes.map(t => t.id) }
          selectedOptions={ selectedEventTypes }
          labels={ schedule.eventTypes.map(t => t.name) }
          onChange={ setSelectedEventTypes } />

        <DebugOptions debug={ debug } currentTime={ currentTime } setCurrentTime={ setCurrentTime } />
      </div>
    );
  }

  return (
    <div className="panel panel-default filters">
      <div className="panel-heading">
        <h2 className="panel-title">
          <span className="title">Filtering options</span>
          <span className="toggle"><a href="#" onClick={ (ev) => { ev.preventDefault(); setVisible(!visible) } }>{ visible ? 'Hide' : 'Show' }</a></span>
        </h2>
      </div>

      { visible && renderBody() }
    </div>
  );
}

export default Filters;
