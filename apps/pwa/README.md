# PWA

Mobile-first React PWA for acquirers and action-scoped roles.

POC-062 proves installability, the update and offline notice, and the business
sponsor and activity interface against real Core sessions, Twenty and the
versioned golden dataset.

POC-043 provides the secured data access for this: the PWA talks only to the
LeonAid Core API and knows neither a Twenty login nor a Twenty key. Lists,
search, counts, export, activities and documents there use the same scope,
derived from session, membership and assignment.
