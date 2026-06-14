package sessionstore

import "testing"

func TestIndexSeekFloor(t *testing.T) {
	var ix index
	ix.add(0.00, 0)
	ix.add(0.10, 4096)
	ix.add(0.20, 8192)
	if off, ok := ix.floorOffset(0.15); !ok || off != 4096 {
		t.Errorf("floorOffset(0.15)=%d,%v want 4096,true", off, ok)
	}
	if off, _ := ix.floorOffset(0.00); off != 0 {
		t.Errorf("floorOffset(0.00)=%d want 0", off)
	}
	if _, ok := ix.floorOffset(-1); ok {
		t.Errorf("floorOffset(-1) should be !ok")
	}
}
