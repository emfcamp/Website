import React from 'react';

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
      <h2>{ newDay && `${hour.toFormat('DD')} - ` }{hour.toFormat('HH:mm')}</h2>
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

export default Calendar;
