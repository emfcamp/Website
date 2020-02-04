import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import ScheduleData from './ScheduleData.js';

function DateTimePicker({ value, onChange }) {
  let date = value.toISODate();
  let time = value.toFormat('HH:mm');

  function dateChanged(ev) {
    let newValue = DateTime.fromISO(`${ev.target.value}T${time}`)
    onChange(newValue);
  }

  function timeChanged(ev) {
    let newValue = DateTime.fromISO(`${date}T${ev.target.value}`)
    onChange(newValue);
  }

  return (
    <>
      <input type="date" value={date} onChange={dateChanged} />
      <input type="time" value={time} onChange={timeChanged} />
    </>
  );
}

function Checkbox({ checked, onChange, children }) {
  return (
    <label className="checkbox"><input type="checkbox" checked={checked} onChange={ ev => onChange(ev.target.checked) } /> { children }</label>
  );
}

function VenueSelector({ venues, selectedVenues, onChange }) {
  function venueToggled(name, value) {
    if (value) {
      onChange([...selectedVenues, name]);
    } else {
      onChange(selectedVenues.filter(v => v !== name));
    }
  }

  function selectOfficialVenues(ev) {
    ev.preventDefault();
    onChange(venues.filter(v => v.official).map(v => v.name));
  }

  function selectAll(ev) {
    ev.preventDefault();
    onChange([...venues.map(v => v.name)]);
  }

  function selectNone(ev) {
    ev.preventDefault();
    onChange([]);
  }

  function checkboxes() {
    return venues.map(venue => {
      return <Checkbox checked={ selectedVenues.indexOf(venue.name) !== -1 } key={ venue.name } onChange={ value => venueToggled(venue.name, value) }>{ venue.name }</Checkbox>;
    });
  }

  return (
    <>
      <p>
        <a href="#" onClick={ selectOfficialVenues }>Official Venues Only</a> | <a href="#" onClick={ selectAll }>Select All</a> | <a href="#" onClick={ selectNone }>Select None</a>
      </p>
      <div className="form-group form-inline">
        { checkboxes() }
      </div>
    </>
  );
}

function Event({ event, abbreviateTitles }) {
  return (
    <div className="schedule-event">
      <h3 title={ event.title } className={ abbreviateTitles ? 'abbreviate-titles' : null }>{ event.title }</h3>
      <p>{ event.startTime.toFormat('HH:mm') } to { event.endTime.toFormat('HH:mm') } | { event.venue }</p>
    </div>
  );
}

function Hour({ hour, content, abbreviateTitles }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-hour">
      <h2>{hour.toFormat('HH:mm')}</h2>
      <div className="schedule-events-container">
        { content.map(event => <Event key={event.id} event={event} abbreviateTitles={abbreviateTitles} />) }
      </div>
    </div>
  );
}

function Calendar({ schedule, abbreviateTitles }) {
  return schedule.hoursWithContent.map(hour => {
    return (
      <Hour key={hour.toISO()} hour={hour} content={schedule.contentForHour(hour)} abbreviateTitles={abbreviateTitles} />
    );
  });
}

function App() {
  const [year, setYear] = useState(2018);
  const [abbreviateTitles, setAbbreviateTitles] = useState(false);
  const [currentTime, setCurrentTime] = useState(DateTime.fromSQL('2018-08-31 09:00:00').setZone('Europe/London'));
  const [selectedVenues, setSelectedVenues] = useState([]);

  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/${year}.json`)
      .then(response => response.json())
      .then(body => {
        setRawSchedule(body)

        let newSchedule = new ScheduleData(body, { currentTime });
        setSchedule(newSchedule);
        setSelectedVenues(newSchedule.venues.map(v => v.name));
      });
  }, [year]);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { currentTime, selectedVenues });
    setSchedule(newSchedule);
  }, [currentTime, selectedVenues]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  function yearChanged(ev) {
    setYear(ev.target.value);
  }

  function currentTimeChanged(newValue) {
    setCurrentTime(newValue);
  }

  return (
    <>
      <h1>Schedule</h1>
      <h3>Venues</h3>
      <VenueSelector venues={ schedule.venues } selectedVenues={ selectedVenues } onChange={ setSelectedVenues } />

      <div className="form-group form-inline">
        <label htmlFor="scheduleYear">Year:</label>
        <select onChange={yearChanged} id="scheduleYear" value={year} className="form-control">
          <option>2012</option>
          <option>2014</option>
          <option>2016</option>
          <option>2018</option>
        </select>
      </div>

      <div className="form-group form-inline">
        <Checkbox checked={ abbreviateTitles } onChange={ setAbbreviateTitles }>Abbreviate titles</Checkbox>
      </div>
      <p>
        <label>Current time:</label>
        <DateTimePicker value={currentTime} onChange={currentTimeChanged} />
      </p>

      <Calendar schedule={ schedule } />
    </>
  )
}

export default App;
