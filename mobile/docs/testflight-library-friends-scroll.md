# TestFlight checklist: Library and Friends scrolling

Run this checklist on the release-candidate TestFlight build. Use at least one
notched iPhone and one Dynamic Island iPhone. Test with both Display Zoom
settings if available.

## Setup

- Sign in to an account with at least 20 saved titles, several watched TV
  series with progress, and a friend who has shared saved and watched titles.
- Use a mix of cached and uncached posters.
- Test once on Wi-Fi and once with Network Link Conditioner set to a slow
  profile.

## Library

- Open **Library**, scroll to the middle, and leave the phone untouched for 15
  seconds. Poster loads and background refreshes must not move the list.
- Pull to refresh from the top, then scroll back to the middle. The list must
  remain responsive and must not jump again when the request finishes.
- While in the middle of the list, switch **All**, **Movies**, and **TV Shows**,
  then change each sort option. The selected control must remain visible and
  the list must not unexpectedly reset to the top.
- Open a title from the middle, wait for its poster and metadata, then use the
  native back gesture. Library should return near the title that was opened.
- On **Watched**, open a TV progress editor. Exercise episode decrement and
  increment, **Watched through this episode**, **Mark season through here**,
  **Mark available series watched**, **Save progress**, and **Toggle this
  episode watched**. Reopen the editor to verify the correction is displayed.
- Confirm the first row starts below the status bar/notch, the bottom row and
  modal actions clear the home indicator, and no content is trapped beneath
  the tab bar.

## Friends comparison

- Open a friend comparison with enough titles to scroll. Scroll to the middle
  and leave it idle for at least 15 seconds. Refresh/poll updates and poster
  loads must not move or reset the page.
- Switch between **Watchlists**, **Watched**, and **For You Both**, including
  each person-specific sub-filter.
- In **Watched both**, confirm separate `You` and friend labels are visible for
  reactions and TV episode progress.
- Open a title from the middle and return with the native back gesture. Confirm
  the comparison returns near the opened title.
- Pull to refresh and verify the spinner stays below the status bar. Confirm
  the back control clears the notch/Dynamic Island and the final row clears the
  home indicator.

## Rotation and accessibility

- Repeat the idle check after portrait → landscape → portrait rotation.
- Repeat at the largest Dynamic Type setting that keeps the app usable.
- Record the device model, iOS version, build number, and a screen recording
  for any unexpected vertical movement.