package rawbuf

import (
	"testing"

	"hil.local/daemon/internal/frame"
)

func TestSincePreservesOrderAndResyncsAfterOverflow(t *testing.T) {
	b := New(4)
	b.Append([]frame.Sample{{TCycles: 1}, {TCycles: 2}, {TCycles: 3}})
	first := b.Since(0, 2)
	if first.Cursor != 2 || len(first.Samples) != 2 ||
		first.Samples[0].TCycles != 1 || first.Samples[1].TCycles != 2 {
		t.Fatalf("first batch: %#v", first)
	}

	b.Append([]frame.Sample{{TCycles: 4}, {TCycles: 5}, {TCycles: 6}})
	overflowed := b.Since(0, 10)
	if overflowed.Cursor != 6 || len(overflowed.Samples) != 4 {
		t.Fatalf("overflowed batch: %#v", overflowed)
	}
	for i, want := range []uint32{3, 4, 5, 6} {
		if overflowed.Samples[i].TCycles != want {
			t.Fatalf("sample[%d]=%d want %d", i, overflowed.Samples[i].TCycles, want)
		}
	}
}

func TestResetAcceptsStaleClientCursor(t *testing.T) {
	b := New(4)
	b.Append([]frame.Sample{{TCycles: 1}, {TCycles: 2}})
	cursor := b.Since(0, 10).Cursor
	b.Reset()
	b.Append([]frame.Sample{{TCycles: 10}})
	got := b.Since(cursor, 10)
	if got.Cursor != 1 || len(got.Samples) != 1 || got.Samples[0].TCycles != 10 {
		t.Fatalf("reset batch: %#v", got)
	}
}

func TestTailSkipsRetainedHistory(t *testing.T) {
	b := New(4)
	b.Append([]frame.Sample{{TCycles: 1}, {TCycles: 2}, {TCycles: 3}})
	if got := b.Since(b.Tail(), 10); got.Cursor != 3 || len(got.Samples) != 0 {
		t.Fatalf("tail batch: %#v", got)
	}
}
