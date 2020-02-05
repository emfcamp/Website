import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import { Checkbox, CheckboxGroup, DateTimePicker } from './Controls.js';

function Filters({ schedule, selectedVenues, setSelectedVenues, selectedEventTypes, setSelectedEventTypes, currentTime, setCurrentTime }) {
  const [visible, setVisible] = useState(false);

  function selectOfficialVenues(ev) {
    ev.preventDefault();
    setSelectedVenues(schedule.venues.filter(v => v.official).map(v => v.name));
  }

  function renderBody() {
    let venueFilters = [
      { name: 'Official Venues Only', callback: selectOfficialVenues }
    ];

    return (
      <div className="panel-body">
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

          <h3>Debug Nonsense</h3>
          <p>
            <label>Current time:</label>
            <DateTimePicker value={currentTime} onChange={setCurrentTime} />
          </p>
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
