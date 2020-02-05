import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import { Checkbox, CheckboxGroup, DateTimePicker } from './Controls.js';
import ScheduleData from './ScheduleData.js';

function Event({ event }) {
  return (
    <div className="schedule-event">
      <h3 title={ event.title }>{ event.title }</h3>
      <p>{ event.startTime.toFormat('HH:mm') } to { event.endTime.toFormat('HH:mm') } | { event.venue }</p>
    </div>
  );
}

function Hour({ hour, content }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-hour">
      <h2>{hour.toFormat('HH:mm')}</h2>
      <div className="schedule-events-container">
        { content.map(event => <Event key={event.id} event={event} />) }
      </div>
    </div>
  );
}

function Calendar({ schedule }) {
  return schedule.hoursWithContent.map(hour => {
    return (
      <Hour key={hour.toISO()} hour={hour} content={schedule.contentForHour(hour)} />
    );
  });
}

function App() {
  const [year, setYear] = useState(2018);
  const [currentTime, setCurrentTime] = useState(DateTime.fromSQL('2018-08-31 09:00:00').setZone('Europe/London'));
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState([]);

  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/${year}.json`)
      .then(response => response.json())
      .then(body => {
        setRawSchedule(body);

        let newSchedule = new ScheduleData(body, { currentTime });
        setSchedule(newSchedule);

        setSelectedVenues(newSchedule.venues.map(v => v.name));
        setSelectedEventTypes([...newSchedule.eventTypes.map(t => t.id)]);
      });
  }, [year]);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { currentTime, selectedVenues, selectedEventTypes });
    setSchedule(newSchedule);
  }, [currentTime, selectedVenues, selectedEventTypes]);

  function selectOfficialVenues(ev) {
    ev.preventDefault();
    setSelectedVenues(schedule.venues.filter(v => v.official).map(v => v.name));
  }

  let venueFilters = [
    { name: 'Official Venues Only', callback: selectOfficialVenues }
  ];

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  return (
    <>
      <h1>Schedule</h1>

      <div className="panel panel-default filters">
        <div className="panel-heading">
          <h2 className="panel-title">Filtering options</h2>
        </div>

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
          <div className="form-group form-inline">
            <label htmlFor="scheduleYear">Year:</label>
            <select onChange={ ev => setYear(ev.target.value) } id="scheduleYear" value={year} className="form-control">
              <option>2012</option>
              <option>2014</option>
              <option>2016</option>
              <option>2018</option>
            </select>
          </div>
          <p>
            <label>Current time:</label>
            <DateTimePicker value={currentTime} onChange={setCurrentTime} />
          </p>
        </div>
      </div>

      <Calendar schedule={ schedule } />
    </>
  );
}

export default App;
