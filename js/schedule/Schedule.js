import React, { useState, useEffect } from 'react';
import ScheduleData from './ScheduleData.js';

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

function Schedule({ year, mainEventsOnly, currentTime, abbreviateTitles }) {
  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/${year}.json`)
      .then(response => response.json())
      .then(body => setRawSchedule(body));
  }, [year]);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { mainEventsOnly, currentTime });
    setSchedule(newSchedule);
  }, [rawSchedule, mainEventsOnly, currentTime]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  function renderContent() {
    return schedule.hoursWithContent.map(hour => {
      return (
        <Hour key={hour.toISO()} hour={hour} content={schedule.contentForHour(hour)} abbreviateTitles={abbreviateTitles} />
      );
    });
  }

  return (
    <div>
      { renderContent() }
    </div>
  );
}

export default Schedule;
