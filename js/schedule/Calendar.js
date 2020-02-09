import React from 'react';
import octicons from '@primer/octicons';

function Icon({ name, className, size, label }) {
  let svg = octicons[name].toSVG({ 'aria-label': label, width: size, height: size });
  return <span className={ className } dangerouslySetInnerHTML={ { __html: svg } } />;
}

function NoRecordingIcon({ mayRecord }) {
  if (mayRecord) { return null; }

  return (
    <div className="no-recording">
      <Icon name="device-camera" className="camera" label="Not recorded" size="16" />
      <Icon name="circle-slash" className="slash" size="32" />
    </div>
  );
}

function FavouriteIcon({ isFavourite }) {
  if (!isFavourite) { return null; }

  return <Icon name="star" className="favourite" size="32" label="Favourite" />;
}

function EventIcons({ mayRecord, isFavourite }) {
  return (
    <div className="event-icons">
      <NoRecordingIcon key='no-recording' mayRecord={ mayRecord } />
      <FavouriteIcon key='favourite' isFavourite={ isFavourite } />
    </div>
  );
}

function Event({ event }) {
  let metadata = [
    `${event.startTime.toFormat('HH:mm')} to ${event.endTime.toFormat('HH:mm')}`,
    event.venue,
    event.speaker,
  ].filter(i => { return i !== null && i !== '' }).join(' | ');

  return (
    <div className="schedule-event">
      <div className="event-data">
        <h3 title={ event.title }>{ event.title }</h3>
        <p>{ metadata }</p>
      </div>
      <EventIcons mayRecord={ event.may_record } isFavourite={ event.isFavourite } />
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
