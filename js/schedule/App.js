import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import { Checkbox, CheckboxGroup, DateTimePicker } from './Controls.js';
import ScheduleData from './ScheduleData.js';

function Event({ event }) {
  let metadata = [
    `${event.startTime.toFormat('HH:mm')} to ${event.endTime.toFormat('HH:mm')}`,
    event.venue,
    event.speaker,
  ].filter(i => { return i !== null && i !== '' }).join(' | ');

  return (
    <div className="schedule-event">
      <h3 title={ event.title }>{ event.title }</h3>
      <p>{ metadata }</p>
    </div>
  );
}

function Hour({ hour, content, newDay }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-hour">
      <h3>{ newDay && `${hour.toFormat('DD')} - ` }{hour.toFormat('HH:mm')}</h3>
      <div className="schedule-events-container">
        { content.map(event => <Event key={event.id} event={event} />) }
      </div>
    </div>
  );
}

function Calendar({ schedule }) {
  let currentDay = null;
  let previousDay = null;
  let newDay = false;

  return schedule.hoursWithContent.map(hour => {
    currentDay = hour.toFormat('DD');
    newDay = currentDay != previousDay;
    previousDay = currentDay;

    return (
      <Hour key={hour.toISO()} hour={hour} newDay={ newDay } content={schedule.contentForHour(hour)} />
    );
  });
}

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

function App() {
  const [currentTime, setCurrentTime] = useState(DateTime.fromSQL('2018-08-31 09:00:00').setZone('Europe/London'));
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState([])

  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/2018.json`)
      .then(response => response.json())
      .then(body => {
        setRawSchedule(body);

        let newSchedule = new ScheduleData(body, { currentTime });
        setSchedule(newSchedule);

        setSelectedVenues(newSchedule.venues.map(v => v.name));
        setSelectedEventTypes([...newSchedule.eventTypes.map(t => t.id)]);
      });
  }, []);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { currentTime, selectedVenues, selectedEventTypes });
    setSchedule(newSchedule);
  }, [currentTime, selectedVenues, selectedEventTypes]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  let filterProps = {
    schedule, selectedVenues, setSelectedVenues, selectedEventTypes, setSelectedEventTypes, currentTime, setCurrentTime
  }

  return (
    <>
      <h1>Schedule</h1>

      <Filters {...filterProps} />
      <Calendar schedule={ schedule } />
    </>
  );
}

export default App;
