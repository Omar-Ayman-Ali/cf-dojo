import java.io.*;
import java.util.*;

// Not public on purpose: javac compiles a non-public class Main from any file name,
// and Codeforces (Java 21) accepts it. Don't add a `package` line.
class Main {
    static final FastReader in = new FastReader(System.in);
    static final PrintWriter out = new PrintWriter(new BufferedWriter(new OutputStreamWriter(System.out)));

    public static void main(String[] args) throws IOException {
        int t = 1;
        // t = in.nextInt();               // uncomment for multi-test input
        while (t-- > 0) solve();
        out.flush();                       // without this you print nothing
    }

    static void solve() throws IOException {
        // your code
    }

    // Arrays.sort(int[]) and Arrays.sort(long[]) are quicksort: Codeforces hacks feed them
    // anti-quicksort tests that make them O(n^2). Sort a boxed Integer[]/Long[] (merge sort),
    // or shuffle first: safeSort(a).
    static void safeSort(long[] a) {
        Random r = new Random();
        for (int i = a.length - 1; i > 0; i--) {
            int j = r.nextInt(i + 1);
            long x = a[i]; a[i] = a[j]; a[j] = x;
        }
        Arrays.sort(a);
    }

    static void safeSort(int[] a) {
        Random r = new Random();
        for (int i = a.length - 1; i > 0; i--) {
            int j = r.nextInt(i + 1);
            int x = a[i]; a[i] = a[j]; a[j] = x;
        }
        Arrays.sort(a);
    }

    // long by default: int * int overflows silently past 2^31 - 1.
    static long[] readLongs(int n) throws IOException {
        long[] a = new long[n];
        for (int i = 0; i < n; i++) a[i] = in.nextLong();
        return a;
    }

    static class FastReader {
        private final BufferedReader br;
        private StringTokenizer st;

        FastReader(InputStream stream) {
            br = new BufferedReader(new InputStreamReader(stream), 1 << 16);
        }

        String next() throws IOException {
            while (st == null || !st.hasMoreTokens()) {
                String line = br.readLine();
                if (line == null) return null;
                st = new StringTokenizer(line);
            }
            return st.nextToken();
        }

        int nextInt() throws IOException { return Integer.parseInt(next()); }

        long nextLong() throws IOException { return Long.parseLong(next()); }

        double nextDouble() throws IOException { return Double.parseDouble(next()); }

        // The rest of the current line (or the next line if the current one is used up).
        String nextLine() throws IOException {
            if (st != null && st.hasMoreTokens()) {
                StringBuilder sb = new StringBuilder(st.nextToken());
                while (st.hasMoreTokens()) sb.append(' ').append(st.nextToken());
                return sb.toString();
            }
            return br.readLine();
        }
    }
}
