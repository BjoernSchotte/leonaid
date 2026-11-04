import {
  ArrowDownUp,
  Filter as FilterIcon,
  Layers,
  Rows3,
  Search,
  X,
} from "lucide-react";
import type { KeyboardEvent, ReactNode, RefObject } from "react";

import { IconButton } from "../button";
import { Kbd } from "../kbd";
import type { ListProperty, ListSort } from "./types";
import type { ListFilter } from "./saved-views";

export interface FilterBarProps<T> {
  readonly title: string;
  readonly query: string;
  readonly onQueryChange: (query: string) => void;
  /** ↓ or Enter in the search box: move to the first row. */
  readonly onLeaveSearch: () => void;
  readonly searchRef: RefObject<HTMLInputElement | null>;
  readonly filters: readonly ListFilter[];
  readonly propertyById: ReadonlyMap<string, ListProperty<T>>;
  readonly groupable: readonly ListProperty<T>[];
  readonly filterButtonRef: RefObject<HTMLButtonElement | null>;
  readonly onAddFilter: () => void;
  readonly onEditFilter: (prop: string, chip: HTMLButtonElement) => void;
  readonly onRemoveFilter: (prop: string) => void;
  readonly onResetFilters: () => void;
  readonly groupBy: string | null;
  readonly onGroupByChange: (groupBy: string | null) => void;
  readonly sorts: readonly ListSort<T>[];
  readonly sort: string;
  readonly onSortChange: (sort: string) => void;
  readonly compact: boolean;
  readonly onCompactChange: (compact: boolean) => void;
}

function chipValue(labels: readonly string[]): string {
  return labels.length > 2
    ? `${labels.slice(0, 2).join(", ")} +${labels.length - 2}`
    : labels.join(", ");
}

/** Search, filter chips, grouping, sort and density (`role="toolbar"`). */
export function FilterBar<T>({
  compact,
  filterButtonRef,
  filters,
  groupBy,
  groupable,
  onAddFilter,
  onCompactChange,
  onEditFilter,
  onGroupByChange,
  onLeaveSearch,
  onQueryChange,
  onRemoveFilter,
  onResetFilters,
  onSortChange,
  propertyById,
  query,
  searchRef,
  sort,
  sorts,
  title,
}: FilterBarProps<T>) {
  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "Enter") {
      event.preventDefault();
      onLeaveSearch();
    }
  };

  const chips: ReactNode[] = [];
  for (const filter of filters) {
    const prop = propertyById.get(filter.prop);
    if (!prop) continue;
    const labels = filter.values.map(
      (value) =>
        prop.options.find((option) => option.value === value)?.label ?? value,
    );
    const PropIcon = prop.icon;
    chips.push(
      <span className="chip" key={filter.prop}>
        <button
          className="chip-main"
          onClick={(event) => onEditFilter(filter.prop, event.currentTarget)}
          type="button"
        >
          <PropIcon aria-hidden="true" size={13} />
          <span className="chip-prop">{prop.label}</span>
          <span className="chip-op">
            {filter.values.length > 1 ? "ist eins von" : "ist"}
          </span>
          <span className="chip-value">{chipValue(labels)}</span>
        </button>
        <button
          aria-label={`Filter ${prop.label} entfernen`}
          className="chip-remove"
          onClick={() => onRemoveFilter(filter.prop)}
          type="button"
        >
          <X aria-hidden="true" size={12} />
        </button>
      </span>,
    );
  }

  return (
    <div aria-label="Listenwerkzeuge" className="toolbar" role="toolbar">
      <label className="search">
        <Search aria-hidden="true" size={15} />
        <span className="sr-only">{`${title} durchsuchen`}</span>
        <input
          enterKeyHint="search"
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={onSearchKeyDown}
          placeholder={`${title} durchsuchen`}
          ref={searchRef}
          role="searchbox"
          type="text"
          value={query}
        />
        {!query ? <Kbd announce={false} keys="/" subtle /> : null}
      </label>

      <div aria-label="Aktive Filter" className="filter-chips" role="group">
        {chips}
        <button
          className="chip-add"
          onClick={onAddFilter}
          ref={filterButtonRef}
          type="button"
        >
          <FilterIcon aria-hidden="true" size={13} />
          Filter
          <Kbd announce={false} keys="f" subtle />
        </button>
        {filters.length > 0 ? (
          <button className="chip-clear" onClick={onResetFilters} type="button">
            Zurücksetzen
          </button>
        ) : null}
      </div>

      <div className="toolbar-end">
        <label className="select-inline">
          <Layers aria-hidden="true" size={14} />
          <span className="sr-only">Gruppieren nach</span>
          <select
            onChange={(event) => onGroupByChange(event.target.value || null)}
            value={groupBy ?? ""}
          >
            <option value="">Keine Gruppen</option>
            {groupable.map((prop) => (
              <option key={prop.id} value={prop.id}>
                {prop.label}
              </option>
            ))}
          </select>
        </label>
        <label className="select-inline">
          <ArrowDownUp aria-hidden="true" size={14} />
          <span className="sr-only">Sortieren</span>
          <select
            onChange={(event) => onSortChange(event.target.value)}
            value={sort}
          >
            {sorts.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <IconButton
          aria-pressed={compact}
          icon={Rows3}
          label={compact ? "Normale Zeilenhöhe" : "Kompakte Zeilen"}
          onClick={() => onCompactChange(!compact)}
        />
      </div>
    </div>
  );
}
